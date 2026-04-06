"""
🔮 Zen Tarot 塔罗项目 · 自动化运营监控脚本
"""

import os
import re
import json
import random
import asyncio
import requests
from datetime import datetime, timezone, timedelta
from supabase import create_client, Client

# ─────────────────────────────────────────────
# 配置
# ─────────────────────────────────────────────
THREADS_URL = "https://www.threads.com/@wangzy2026/post/DWgLFq3iWxc"

SUPABASE_URL = "https://ybragvmvirddqfotqxig.supabase.co"
SUPABASE_KEY = (
    os.environ.get("SUPABASE_KEY")
    or "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InlicmFndm12aXJkZHFmb3RxeGlnIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzQ4MzgzNDcsImV4cCI6MjA5MDQxNDM0N30.4UKQfcVHjbHPEdOIiWjixswk7qVz5nNsNRL5VG9UQY0"
)

FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/db9c21f0-9453-410d-ae0e-c9116a8dc612"
BEIJING_TZ = timezone(timedelta(hours=8))

# ─────────────────────────────────────────────
# 工具
# ─────────────────────────────────────────────

def beijing_today_utc_range():
    """北京时间今日 00:00 ~ 明日 00:00 → UTC ISO 字符串"""
    now_bj = datetime.now(BEIJING_TZ)
    start_bj = now_bj.replace(hour=0, minute=0, second=0, microsecond=0)
    end_bj = start_bj + timedelta(days=1)
    fmt = "%Y-%m-%dT%H:%M:%S+00:00"
    return (
        start_bj.astimezone(timezone.utc).strftime(fmt),
        end_bj.astimezone(timezone.utc).strftime(fmt),
    )

def now_bj_str():
    return datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S")

def fmt_num(val):
    if val in ("N/A", None, ""):
        return "N/A"
    try:
        return f"{int(str(val).replace(',', '')):,}"
    except Exception:
        return str(val)


# ─────────────────────────────────────────────
# 1. Threads 抓取
# ─────────────────────────────────────────────

async def scrape_threads() -> dict:
    from playwright.async_api import async_playwright

    result = {
        "views": "N/A", "likes": "N/A",
        "reposts": "N/A", "replies": "N/A",
        "comments": [], "error": None,
    }

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox", "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1440, "height": 900},
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
        )
        await context.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
            "window.chrome={runtime:{}};"
        )

        # 拦截 GraphQL 响应
        api_payloads = []
        page = await context.new_page()

        async def capture_response(response):
            if "graphql" in response.url:
                try:
                    body = await response.json()
                    api_payloads.append(body)
                except Exception:
                    pass

        page.on("response", capture_response)
        await page.route(
            "**/*.{png,jpg,jpeg,gif,webp,mp4,webm,woff,woff2}",
            lambda r: r.abort()
        )

        try:
            print(f"[Threads] 访问: {THREADS_URL}")
            await page.goto(THREADS_URL, wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(random.uniform(5, 8))

            try:
                await page.wait_for_selector(
                    'article, [role="article"], div[data-pressable-container]',
                    timeout=12000
                )
            except Exception:
                pass

            # 滚动触发更多内容加载
            await page.evaluate("window.scrollBy(0, 800)")
            await asyncio.sleep(random.uniform(2, 3))
            await page.evaluate("window.scrollBy(0, 800)")
            await asyncio.sleep(random.uniform(1, 2))

            html = await page.content()

            # 把内嵌 JSON script 也加入
            for block in re.findall(
                r'<script[^>]*type=["\']application/json["\'][^>]*>(.*?)</script>',
                html, re.DOTALL
            ):
                try:
                    api_payloads.append(json.loads(block))
                except Exception:
                    pass

            all_json_str = json.dumps(api_payloads, ensure_ascii=False)

            # ── 提取帖子指标 ──────────────────────────────
            field_map = {
                "likes":   ["like_count", "likeCount"],
                "reposts": ["repost_count", "repostCount", "reshare_count"],
                "replies": ["reply_count", "replyCount", "direct_reply_count"],
                "views":   ["play_count", "view_count", "viewCount",
                            "video_play_count", "impression_count"],
            }
            # 先从 GraphQL + JSON 提取
            for field, keys in field_map.items():
                for key in keys:
                    m = re.search(rf'"{key}"\s*:\s*(\d+)', all_json_str)
                    if m:
                        result[field] = m.group(1)
                        break
            # 再从原始 HTML 兜底
            for field, keys in field_map.items():
                if result[field] != "N/A":
                    continue
                for key in keys:
                    m = re.search(rf'"{key}"\s*:\s*(\d+)', html)
                    if m:
                        result[field] = m.group(1)
                        break
            # aria-label 最后兜底
            try:
                labels = await page.evaluate(
                    "()=>Array.from(document.querySelectorAll('[aria-label]'))"
                    ".map(e=>e.getAttribute('aria-label'))"
                    ".filter(l=>l&&/\\d/.test(l))"
                )
                for label in labels:
                    ll = label.lower()
                    num_m = re.search(r'([\d,]+)', label)
                    if not num_m:
                        continue
                    num = num_m.group(1)
                    if result["likes"] == "N/A" and ("like" in ll or "赞" in ll):
                        result["likes"] = num
                    if result["reposts"] == "N/A" and ("repost" in ll or "转发" in ll):
                        result["reposts"] = num
                    if result["replies"] == "N/A" and ("repl" in ll or "回复" in ll):
                        result["replies"] = num
            except Exception:
                pass

            # ── 提取最新 10 条评论（按时间倒序）────────────
            # 策略：从 GraphQL payload 提取评论对象，保留时间戳用于排序
            comment_objs = []  # [{text, timestamp}]

            for payload in api_payloads:
                dumped = json.dumps(payload, ensure_ascii=False)
                # 找所有含 text + taken_at 的评论对象
                # Threads 评论结构：{"text":"...","taken_at":1234567890,...}
                matches = re.finditer(
                    r'"taken_at"\s*:\s*(\d+).*?"text"\s*:\s*"((?:[^"\\]|\\.){8,300})"'
                    r'|"text"\s*:\s*"((?:[^"\\]|\\.){8,300})".*?"taken_at"\s*:\s*(\d+)',
                    dumped
                )
                for m in matches:
                    if m.group(1):
                        ts, text = int(m.group(1)), m.group(2)
                    else:
                        ts, text = int(m.group(4)), m.group(3)
                    text = text.replace("\\n", " ").replace('\\"', '"').strip()
                    comment_objs.append({"text": text, "ts": ts})

            # 去重 + 按时间倒序
            seen_texts = set()
            unique_comments = []
            for obj in sorted(comment_objs, key=lambda x: x["ts"], reverse=True):
                t = obj["text"]
                if t not in seen_texts:
                    seen_texts.add(t)
                    unique_comments.append(t)
                if len(unique_comments) >= 10:
                    break

            # DOM 兜底（如果 GraphQL 没拿到评论）
            if len(unique_comments) < 3:
                selectors = [
                    'div[data-pressable-container] span[dir="auto"]',
                    'article span[dir="auto"]',
                    '[role="article"] span[dir="auto"]',
                ]
                for sel in selectors:
                    try:
                        nodes = await page.query_selector_all(sel)
                        for node in nodes:
                            t = (await node.inner_text()).strip()
                            if 8 <= len(t) <= 300 and t not in seen_texts:
                                seen_texts.add(t)
                                unique_comments.append(t)
                    except Exception:
                        pass

            result["comments"] = unique_comments[:10]

            print(
                f"[Threads] views={result['views']} | likes={result['likes']} | "
                f"reposts={result['reposts']} | replies={result['replies']} | "
                f"comments={len(result['comments'])}条"
            )

        except Exception as e:
            result["error"] = str(e)
            print(f"[Threads] 异常: {e}")
        finally:
            await context.close()
            await browser.close()

    return result


# ─────────────────────────────────────────────
# 2. Supabase 统计
# 表名：tarot_history
# 字段：id, created_at, card_name, is_reversed,
#       spread_type, anonymous_id, question
#
# 翻牌次数逻辑：
#   一次占卜插入 1/3/10 行（每张牌一行），
#   用 DISTINCT anonymous_id + created_at 去重才是真实占卜次数
# ─────────────────────────────────────────────

def query_supabase() -> dict:
    stats = {
        "today_flips": 0,
        "total_flips": 0,
        "today_questions": [],
        "error": None,
    }

    try:
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        start_utc, end_utc = beijing_today_utc_range()
        print(f"[Supabase] 北京今日 UTC: {start_utc} ~ {end_utc}")

        # ── 今日翻牌次数（真实去重）──────────────────
        # 每次占卜的所有牌共享同一个 anonymous_id + created_at（同秒）
        # 用 DISTINCT(anonymous_id, created_at) 计数
        # Supabase Python SDK 不直接支持 DISTINCT 聚合，改用 RPC 或拉数据在 Python 去重
        today_rows = (
            supabase.table("tarot_history")
            .select("anonymous_id, created_at")
            .gte("created_at", start_utc)
            .lt("created_at", end_utc)
            .execute()
        )
        today_data = today_rows.data or []
        # Python 端去重：同一个 anonymous_id 在同一秒的算一次
        today_sessions = set()
        for row in today_data:
            anon = row.get("anonymous_id", "")
            # 截断到秒级做去重 key
            created = str(row.get("created_at", ""))[:19]
            today_sessions.add(f"{anon}|{created}")
        stats["today_flips"] = len(today_sessions)

        # ── 累计总翻牌次数（真实去重）───────────────
        # 数据量大，分批拉可能很慢；改用 count 行数 / 平均牌数 近似，
        # 或拉全量去重（163K 行约 1~2s）
        total_rows = (
            supabase.table("tarot_history")
            .select("anonymous_id, created_at")
            .execute()
        )
        total_data = total_rows.data or []
        total_sessions = set()
        for row in total_data:
            anon = row.get("anonymous_id", "")
            created = str(row.get("created_at", ""))[:19]
            total_sessions.add(f"{anon}|{created}")
        stats["total_flips"] = len(total_sessions)

        # ── 今日去重问题（最新 100 条）───────────────
        # 问题字段名：question
        q_rows = (
            supabase.table("tarot_history")
            .select("question, created_at")
            .gte("created_at", start_utc)
            .lt("created_at", end_utc)
            .not_.is_("question", "null")
            .order("created_at", desc=True)
            .limit(500)
            .execute()
        )
        seen_q, unique_q = set(), []
        for row in (q_rows.data or []):
            q = (row.get("question") or "").strip()
            if q and q not in seen_q:
                seen_q.add(q)
                unique_q.append(q)
            if len(unique_q) >= 100:
                break
        stats["today_questions"] = unique_q

        print(
            f"[Supabase] 今日翻牌={stats['today_flips']} | 总翻牌={stats['total_flips']} | "
            f"今日问题={len(stats['today_questions'])}条"
        )

    except Exception as e:
        stats["error"] = str(e)
        print(f"[Supabase] 异常: {e}")

    return stats


# ─────────────────────────────────────────────
# 3. 飞书富文本卡片
# ─────────────────────────────────────────────

def send_feishu(threads: dict, db: dict):
    run_time = now_bj_str()
    questions = db.get("today_questions", [])

    # 评论区块
    if threads["comments"]:
        comments_md = "\n".join(
            f"{i}. {c[:120]}{'…' if len(c) > 120 else ''}"
            for i, c in enumerate(threads["comments"], 1)
        )
    else:
        comments_md = "（暂未获取到回复内容）"

    # 问题区块（前 20 条展示，全部存档）
    if questions:
        q_lines = "\n".join(
            f"{i}. {q[:80]}{'…' if len(q) > 80 else ''}"
            for i, q in enumerate(questions[:20], 1)
        )
        if len(questions) > 20:
            q_lines += f"\n… 共 {len(questions)} 条，仅展示最新 20 条"
    else:
        q_lines = "（今日暂无问题）"

    threads_err = f"\n⚠️ 抓取异常：{threads['error']}" if threads.get("error") else ""
    db_err = f"\n⚠️ 数据库异常：{db['error']}" if db.get("error") else ""

    card = {
        "msg_type": "interactive",
        "card": {
            "schema": "2.0",
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": "🔮 塔罗项目·今日运营深度看板"
                },
                "template": "purple",
            },
            "body": {
                "elements": [
                    {
                        "tag": "markdown",
                        "content": f"**📅 报告时间：** {run_time}（北京时间）"
                    },
                    {"tag": "hr"},

                    # Threads 数据
                    {
                        "tag": "markdown",
                        "content": (
                            "**📱 Threads 帖子数据**\n"
                            f"👁 浏览量：**{fmt_num(threads['views'])}**　　"
                            f"❤️ 点赞：**{fmt_num(threads['likes'])}**\n"
                            f"🔁 转发：**{fmt_num(threads['reposts'])}**　　"
                            f"💬 回复数：**{fmt_num(threads['replies'])}**"
                            f"{threads_err}"
                        ),
                    },
                    {"tag": "hr"},

                    # 最新回复内容（时间倒序）
                    {
                        "tag": "markdown",
                        "content": f"**💬 最新 10 条回复内容（时间倒序）**\n{comments_md}"
                    },
                    {"tag": "hr"},

                    # 翻牌统计
                    {
                        "tag": "markdown",
                        "content": (
                            "**🃏 翻牌数据统计（北京时间今日零点起）**\n"
                            f"🌅 今日翻牌次数：**{fmt_num(db['today_flips'])}** 次\n"
                            f"📊 累计总翻牌次数：**{fmt_num(db['total_flips'])}** 次\n"
                            f"*（已按 anonymous_id + 时间戳去重，排除同次占卜多张牌的重复行）*"
                            f"{db_err}"
                        ),
                    },
                    {"tag": "hr"},

                    # 今日用户问题
                    {
                        "tag": "markdown",
                        "content": (
                            f"**❓ 今日用户提问（去重后共 {len(questions)} 条）**\n{q_lines}"
                        )
                    },
                    {"tag": "hr"},

                    {
                        "tag": "markdown",
                        "content": "🤖 *由 GitHub Actions 定时触发 · Zen Tarot 运营机器人*"
                    },
                ]
            },
        },
    }

    try:
        resp = requests.post(FEISHU_WEBHOOK, json=card, timeout=15)
        resp.raise_for_status()
        r = resp.json()
        print(f"[飞书] {'发送成功 ✅' if r.get('code') == 0 else f'失败: {r}'}")
    except Exception as e:
        print(f"[飞书] 异常: {e}")


# ─────────────────────────────────────────────
# 主入口
# ─────────────────────────────────────────────

async def main():
    print("=" * 60)
    print(f"🔮 Zen Tarot 监控启动 @ {now_bj_str()}")
    print("=" * 60)

    print("\n▶ Step 1 / 抓取 Threads")
    threads_data = await scrape_threads()

    print("\n▶ Step 2 / 查询 Supabase")
    supabase_data = query_supabase()

    print("\n▶ Step 3 / 发送飞书通知")
    send_feishu(threads_data, supabase_data)

    print("\n✅ 全部完成！")


if __name__ == "__main__":
    asyncio.run(main())
