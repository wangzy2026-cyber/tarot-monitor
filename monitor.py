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
    """返回北京时间今日 00:00 ~ 明日 00:00 对应的 UTC ISO 字符串"""
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
    """把数字字符串格式化为带千分位的形式，N/A 原样返回"""
    if val == "N/A" or val is None:
        return "N/A"
    try:
        return f"{int(str(val).replace(',','')):,}"
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
                "--no-sandbox",
                "--disable-setuid-sandbox",
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

        page = await context.new_page()
        # 屏蔽媒体资源，加速加载
        await page.route(
            "**/*.{png,jpg,jpeg,gif,webp,mp4,webm,woff,woff2,svg}",
            lambda r: r.abort()
        )

        # 拦截 XHR/Fetch，捕获 Threads GraphQL 响应
        api_payloads = []
        def handle_response(response):
            url = response.url
            if "api/graphql" in url or "graphql" in url:
                async def capture():
                    try:
                        body = await response.json()
                        api_payloads.append(body)
                    except Exception:
                        pass
                asyncio.ensure_future(capture())
        page.on("response", handle_response)

        try:
            print(f"[Threads] 访问: {THREADS_URL}")
            await page.goto(THREADS_URL, wait_until="domcontentloaded", timeout=60000)

            # 等待 JS 渲染
            await asyncio.sleep(random.uniform(5, 8))
            try:
                await page.wait_for_selector(
                    'article, [role="article"], div[data-pressable-container]',
                    timeout=12000
                )
            except Exception:
                pass
            await asyncio.sleep(random.uniform(1, 2))
            await page.evaluate("window.scrollBy(0, 500)")
            await asyncio.sleep(random.uniform(1.5, 2.5))

            html = await page.content()

            # ── 解析：从拦截的 GraphQL JSON 提取 ──────────
            all_json_str = json.dumps(api_payloads)
            # 也把页面内嵌 script JSON 一起搜
            inline_jsons = re.findall(
                r'<script[^>]*type=["\']application/json["\'][^>]*>(.*?)</script>',
                html, re.DOTALL
            )
            for block in inline_jsons:
                try:
                    api_payloads.append(json.loads(block))
                except Exception:
                    pass
            all_json_str = json.dumps(api_payloads)

            field_map = {
                "likes":   ["like_count", "likeCount"],
                "reposts": ["repost_count", "repostCount", "reshare_count"],
                "replies": ["reply_count", "replyCount", "direct_reply_count"],
                "views":   ["play_count", "view_count", "viewCount", "video_play_count",
                            "impression_count", "reach_count"],
            }
            for field, keys in field_map.items():
                if result[field] != "N/A":
                    continue
                for key in keys:
                    m = re.search(rf'"{key}"\s*:\s*(\d+)', all_json_str)
                    if m:
                        result[field] = m.group(1)
                        break

            # ── 备用：直接搜原始 HTML ──────────────────────
            for field, keys in field_map.items():
                if result[field] != "N/A":
                    continue
                for key in keys:
                    m = re.search(rf'"{key}"\s*:\s*(\d+)', html)
                    if m:
                        result[field] = m.group(1)
                        break

            # ── 备用：aria-label 提取 ──────────────────────
            if any(result[f] == "N/A" for f in ["likes", "reposts", "replies"]):
                try:
                    labels = await page.evaluate(
                        "() => Array.from(document.querySelectorAll('[aria-label]'))"
                        ".map(el=>el.getAttribute('aria-label'))"
                        ".filter(l=>l&&/\\d/.test(l))"
                    )
                    for label in labels:
                        ll = label.lower()
                        if result["likes"] == "N/A" and ("like" in ll or "赞" in ll):
                            m = re.search(r'([\d,]+)', label)
                            if m: result["likes"] = m.group(1)
                        if result["reposts"] == "N/A" and ("repost" in ll or "转发" in ll):
                            m = re.search(r'([\d,]+)', label)
                            if m: result["reposts"] = m.group(1)
                        if result["replies"] == "N/A" and ("repl" in ll or "回复" in ll):
                            m = re.search(r'([\d,]+)', label)
                            if m: result["replies"] = m.group(1)
                except Exception:
                    pass

            # ── 抓取今日新增回复内容（最新 10 条）────────────
            # 优先从 GraphQL payload 提取评论文本
            comment_texts = []
            for payload in api_payloads:
                dumped = json.dumps(payload, ensure_ascii=False)
                # Threads 评论文本一般在 text_with_entities.text 或 caption.text
                texts = re.findall(r'"text"\s*:\s*"((?:[^"\\]|\\.){8,200})"', dumped)
                for t in texts:
                    t = t.replace("\\n", " ").replace('\\"', '"').strip()
                    if t not in comment_texts and len(t) >= 8:
                        comment_texts.append(t)
                if len(comment_texts) >= 30:
                    break

            # DOM 选择器兜底
            if len(comment_texts) < 5:
                selectors = [
                    'div[data-pressable-container] span[dir="auto"]',
                    'article span[dir="auto"]',
                    '[role="article"] span[dir="auto"]',
                ]
                seen = set(comment_texts)
                for sel in selectors:
                    try:
                        nodes = await page.query_selector_all(sel)
                        for node in nodes:
                            t = (await node.inner_text()).strip()
                            if 8 <= len(t) <= 300 and t not in seen:
                                seen.add(t)
                                comment_texts.append(t)
                    except Exception:
                        pass

            # 去掉帖子原文（第一条通常是作者自己的内容）
            result["comments"] = comment_texts[:10]

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
# ─────────────────────────────────────────────

def query_supabase() -> dict:
    stats = {
        "today_visits": 0,    # 今日访问量（页面访问记录，如有）
        "today_flips": 0,     # 今日翻牌数
        "total_flips": 0,     # 累计总翻牌数
        "today_questions": [], # 今日去重问题
        "error": None,
    }

    try:
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        start_utc, end_utc = beijing_today_utc_range()
        print(f"[Supabase] 北京今日 UTC 范围: {start_utc}  ~  {end_utc}")

        # ── 今日翻牌数 ──────────────────────────────────
        today_resp = (
            supabase.table("readings")
            .select("id", count="exact")
            .gte("created_at", start_utc)
            .lt("created_at", end_utc)
            .execute()
        )
        stats["today_flips"] = today_resp.count or 0

        # ── 累计总翻牌数 ────────────────────────────────
        total_resp = (
            supabase.table("readings")
            .select("id", count="exact")
            .execute()
        )
        stats["total_flips"] = total_resp.count or 0

        # ── 今日访问量（尝试 page_views 表，不存在则跳过）──
        try:
            visit_resp = (
                supabase.table("page_views")
                .select("id", count="exact")
                .gte("created_at", start_utc)
                .lt("created_at", end_utc)
                .execute()
            )
            stats["today_visits"] = visit_resp.count or 0
        except Exception:
            stats["today_visits"] = None  # 表不存在，不报错

        # ── 今日去重问题（最新 100 条）──────────────────
        q_resp = (
            supabase.table("readings")
            .select("question, created_at")
            .gte("created_at", start_utc)
            .lt("created_at", end_utc)
            .not_.is_("question", "null")
            .order("created_at", desc=True)
            .limit(300)
            .execute()
        )
        seen_q, unique_q = set(), []
        for row in (q_resp.data or []):
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
# 3. 飞书通知
# ─────────────────────────────────────────────

def send_feishu(threads: dict, db: dict):
    run_time = now_bj_str()
    questions = db.get("today_questions", [])

    # 评论区块
    if threads["comments"]:
        comments_md = "\n".join(
            f"{i}. {c[:100]}{'…' if len(c) > 100 else ''}"
            for i, c in enumerate(threads["comments"], 1)
        )
    else:
        comments_md = "（暂未获取到回复内容）"

    # 问题区块
    if questions:
        q_md = "\n".join(
            f"{i}. {q[:80]}{'…' if len(q) > 80 else ''}"
            for i, q in enumerate(questions[:20], 1)
        )
        if len(questions) > 20:
            q_md += f"\n… 共 {len(questions)} 条，展示前 20 条"
    else:
        q_md = "（今日暂无问题）"

    threads_err = f"\n⚠️ {threads['error']}" if threads.get("error") else ""
    db_err = f"\n⚠️ {db['error']}" if db.get("error") else ""

    # 访问量行（可选）
    visit_line = ""
    if db.get("today_visits") is not None:
        visit_line = f"🌐 今日访问量：**{fmt_num(db['today_visits'])}** 次\n"

    card = {
        "msg_type": "interactive",
        "card": {
            "schema": "2.0",
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": "🔮 塔罗项目·今日运营深度看板"},
                "template": "purple",
            },
            "body": {
                "elements": [
                    # 报告时间
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
                            f"💬 回复：**{fmt_num(threads['replies'])}**"
                            f"{threads_err}"
                        ),
                    },
                    {"tag": "hr"},

                    # 今日新增回复
                    {
                        "tag": "markdown",
                        "content": f"**💬 最新 10 条回复内容**\n{comments_md}"
                    },
                    {"tag": "hr"},

                    # Supabase 翻牌统计
                    {
                        "tag": "markdown",
                        "content": (
                            "**🗃️ 翻牌数据统计**\n"
                            f"{visit_line}"
                            f"🌅 今日翻牌（北京时间）：**{fmt_num(db['today_flips'])}** 次\n"
                            f"📊 累计总翻牌：**{fmt_num(db['total_flips'])}** 次"
                            f"{db_err}"
                        ),
                    },
                    {"tag": "hr"},

                    # 今日用户问题
                    {
                        "tag": "markdown",
                        "content": (
                            f"**❓ 今日用户提问（去重后共 {len(questions)} 条）**\n{q_md}"
                        )
                    },
                    {"tag": "hr"},

                    # 底部
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
