"""
🔮 Zen Tarot 塔罗项目 · 自动化运营监控脚本
功能：抓取 Threads 数据 + Supabase 统计 + 飞书通知
"""

import os
import re
import json
import time
import random
import asyncio
import requests
from datetime import datetime, timezone, timedelta
from supabase import create_client, Client

# ─────────────────────────────────────────────
# 配置区
# ─────────────────────────────────────────────
THREADS_URL = "https://www.threads.net/@wangzy2026/post/DWgLFq3iWxc"

SUPABASE_URL = "https://ybragvmvirddqfotqxig.supabase.co"
# 优先读环境变量，fallback 到硬编码（Secret 未配置时保底）
SUPABASE_KEY = (
    os.environ.get("SUPABASE_KEY")
    or "sb_publishable_Kf3_0KgYnDX62_Tk6QbrBA_3zeEIjm9"
)

FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/db9c21f0-9453-410d-ae0e-c9116a8dc612"
BEIJING_TZ = timezone(timedelta(hours=8))

# ─────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────

def beijing_today_utc_range():
    now_bj = datetime.now(BEIJING_TZ)
    start_bj = now_bj.replace(hour=0, minute=0, second=0, microsecond=0)
    end_bj = start_bj + timedelta(days=1)
    start_utc = start_bj.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    end_utc = end_bj.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    return start_utc, end_utc

def now_bj_str():
    return datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S")

def parse_count(text: str) -> str:
    """从字符串中提取数字，支持 1.2K / 3.4M 等格式"""
    if not text:
        return "N/A"
    text = text.strip()
    m = re.search(r'([\d,]+\.?\d*\s*[KMBkmb]?)', text)
    if m:
        return m.group(1).replace(" ", "")
    return "N/A"

# ─────────────────────────────────────────────
# 1. Threads 数据抓取（Playwright）
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
                "--disable-web-security",
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

        # 注入 stealth：覆盖 webdriver 检测
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
            window.chrome = { runtime: {} };
        """)

        page = await context.new_page()
        await page.route("**/*.{png,jpg,jpeg,gif,webp,mp4,webm,woff,woff2}", lambda r: r.abort())

        try:
            print(f"[Threads] 访问: {THREADS_URL}")
            await page.goto(THREADS_URL, wait_until="domcontentloaded", timeout=60000)

            # 等待页面 JS 渲染完成（Threads 是 SPA）
            await asyncio.sleep(random.uniform(4, 7))

            # 尝试等待帖子内容出现
            try:
                await page.wait_for_selector('article, [role="article"], div[data-pressable-container]', timeout=15000)
            except Exception:
                print("[Threads] 未找到 article 选择器，继续尝试解析")

            await asyncio.sleep(random.uniform(1, 2))

            # 随机滚动模拟真人
            await page.evaluate("window.scrollBy(0, Math.random() * 400 + 200)")
            await asyncio.sleep(random.uniform(1, 2))

            html = await page.content()

            # ── 策略1：从页面内嵌 JSON 数据提取（最可靠）────────
            # Threads 会把帖子数据注入到 window.__additionalData 或 script[type=application/json]
            json_blocks = re.findall(r'<script[^>]*type=["\']application/json["\'][^>]*>(.*?)</script>', html, re.DOTALL)
            for block in json_blocks:
                try:
                    data = json.loads(block)
                    dumped = json.dumps(data)
                    # 提取 like_count / reply_count / repost_count / play_count
                    for key, field in [
                        ("like_count", "likes"),
                        ("reply_count", "replies"),
                        ("repost_count", "reposts"),
                        ("play_count", "views"),
                        ("view_count", "views"),
                    ]:
                        if result[field] == "N/A":
                            m = re.search(rf'"{key}"\s*:\s*(\d+)', dumped)
                            if m:
                                result[field] = m.group(1)
                except Exception:
                    continue

            # ── 策略2：从原始 HTML 正则提取 ───────────────────
            patterns = {
                "likes":   [r'"like_count"\s*:\s*(\d+)', r'"likeCount"\s*:\s*(\d+)'],
                "replies": [r'"reply_count"\s*:\s*(\d+)', r'"replyCount"\s*:\s*(\d+)'],
                "reposts": [r'"repost_count"\s*:\s*(\d+)', r'"repostCount"\s*:\s*(\d+)'],
                "views":   [r'"play_count"\s*:\s*(\d+)', r'"view_count"\s*:\s*(\d+)', r'"viewCount"\s*:\s*(\d+)'],
            }
            for field, pats in patterns.items():
                if result[field] == "N/A":
                    for pat in pats:
                        m = re.search(pat, html)
                        if m:
                            result[field] = m.group(1)
                            break

            # ── 策略3：从页面可见文字提取数字 ────────────────
            if any(v == "N/A" for v in [result["likes"], result["replies"], result["reposts"]]):
                # 获取所有带数字的 aria-label
                labels = await page.evaluate("""
                    () => Array.from(document.querySelectorAll('[aria-label]'))
                         .map(el => el.getAttribute('aria-label'))
                         .filter(l => l && /\\d/.test(l))
                """)
                for label in labels:
                    label_l = label.lower()
                    if result["likes"] == "N/A" and ("like" in label_l or "赞" in label_l):
                        result["likes"] = parse_count(label)
                    if result["replies"] == "N/A" and ("repl" in label_l or "回复" in label_l or "comment" in label_l):
                        result["replies"] = parse_count(label)
                    if result["reposts"] == "N/A" and ("repost" in label_l or "转发" in label_l or "share" in label_l):
                        result["reposts"] = parse_count(label)

            # ── 抓取最新评论（文本节点）────────────────────────
            comment_selectors = [
                'div[data-pressable-container] span[dir="auto"]',
                'article span[dir="auto"]',
                '[role="article"] span[dir="auto"]',
                'div[class*="comment"] span',
                'div[class*="reply"] span',
            ]
            seen, comments = set(), []
            for sel in comment_selectors:
                if len(comments) >= 10:
                    break
                try:
                    nodes = await page.query_selector_all(sel)
                    for node in nodes:
                        text = (await node.inner_text()).strip()
                        if 8 <= len(text) <= 300 and text not in seen:
                            seen.add(text)
                            comments.append(text)
                        if len(comments) >= 10:
                            break
                except Exception:
                    continue
            result["comments"] = comments

            print(f"[Threads] views={result['views']}, likes={result['likes']}, "
                  f"reposts={result['reposts']}, replies={result['replies']}, "
                  f"comments={len(result['comments'])}条")

        except Exception as e:
            result["error"] = str(e)
            print(f"[Threads] 异常: {e}")
        finally:
            await context.close()
            await browser.close()

    return result


# ─────────────────────────────────────────────
# 2. Supabase 数据统计
# ─────────────────────────────────────────────

def query_supabase() -> dict:
    stats = {
        "today_flips": 0, "total_flips": 0,
        "today_questions": [], "error": None,
    }

    print(f"[Supabase] 使用 Key: {SUPABASE_KEY[:20]}...")

    try:
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        start_utc, end_utc = beijing_today_utc_range()
        print(f"[Supabase] 今日 UTC 范围: {start_utc} ~ {end_utc}")

        # ── 今日翻牌数 ──────────────────────────────────
        try:
            today_resp = (
                supabase.table("readings")
                .select("id", count="exact")
                .gte("created_at", start_utc)
                .lt("created_at", end_utc)
                .execute()
            )
            stats["today_flips"] = today_resp.count or 0
        except Exception as e:
            print(f"[Supabase] 今日翻牌查询失败: {e}")

        # ── 总翻牌数 ────────────────────────────────────
        try:
            total_resp = (
                supabase.table("readings")
                .select("id", count="exact")
                .execute()
            )
            stats["total_flips"] = total_resp.count or 0
        except Exception as e:
            print(f"[Supabase] 总翻牌查询失败: {e}")

        # ── 今日问题（去重）────────────────────────────
        try:
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
        except Exception as e:
            print(f"[Supabase] 问题查询失败: {e}")

        print(f"[Supabase] 今日={stats['today_flips']}, 总计={stats['total_flips']}, "
              f"问题={len(stats['today_questions'])}条")

    except Exception as e:
        stats["error"] = str(e)
        print(f"[Supabase] 连接失败: {e}")

    return stats


# ─────────────────────────────────────────────
# 3. 飞书富文本卡片通知
# ─────────────────────────────────────────────

def send_feishu(threads_data: dict, supabase_data: dict):
    run_time = now_bj_str()
    questions = supabase_data.get("today_questions", [])

    # 评论列表
    if threads_data.get("comments"):
        comments_text = "\n".join(
            f"{i}. {c[:80]}{'…' if len(c) > 80 else ''}"
            for i, c in enumerate(threads_data["comments"][:10], 1)
        )
    else:
        comments_text = "（暂无评论数据 / Threads 未返回内容）"

    # 问题列表
    if questions:
        q_lines = "\n".join(
            f"{i}. {q[:60]}{'…' if len(q) > 60 else ''}"
            for i, q in enumerate(questions[:20], 1)
        )
        if len(questions) > 20:
            q_lines += f"\n… 共 {len(questions)} 条（展示前 20 条）"
    else:
        q_lines = "（今日暂无问题）"

    threads_err = f"\n⚠️ 抓取异常：{threads_data['error']}" if threads_data.get("error") else ""
    db_err = f"\n⚠️ 数据库异常：{supabase_data['error']}" if supabase_data.get("error") else ""

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
                    {"tag": "markdown", "content": f"**📅 报告时间：** {run_time}（北京时间）"},
                    {"tag": "hr"},
                    {
                        "tag": "markdown",
                        "content": (
                            "**📱 Threads 帖子数据**\n"
                            f"👁️ 浏览量：**{threads_data['views']}**　"
                            f"❤️ 点赞：**{threads_data['likes']}**　"
                            f"🔁 转发：**{threads_data['reposts']}**　"
                            f"💬 回复：**{threads_data['replies']}**"
                            f"{threads_err}"
                        ),
                    },
                    {"tag": "hr"},
                    {"tag": "markdown", "content": f"**💬 最新 10 条评论**\n{comments_text}"},
                    {"tag": "hr"},
                    {
                        "tag": "markdown",
                        "content": (
                            "**🗃️ 翻牌数据统计**\n"
                            f"🌅 今日翻牌（北京时间）：**{supabase_data['today_flips']}** 次\n"
                            f"📊 累计总翻牌：**{supabase_data['total_flips']}** 次"
                            f"{db_err}"
                        ),
                    },
                    {"tag": "hr"},
                    {"tag": "markdown", "content": f"**❓ 今日用户提问（去重后共 {len(questions)} 条）**\n{q_lines}"},
                    {"tag": "hr"},
                    {"tag": "markdown", "content": "🤖 *由 GitHub Actions 定时触发 · Zen Tarot 运营机器人*"},
                ]
            },
        },
    }

    try:
        resp = requests.post(FEISHU_WEBHOOK, json=card, timeout=15)
        resp.raise_for_status()
        r = resp.json()
        if r.get("code") == 0:
            print("[飞书] 发送成功 ✅")
        else:
            print(f"[飞书] 发送失败: {r}")
    except Exception as e:
        print(f"[飞书] 异常: {e}")


# ─────────────────────────────────────────────
# 主函数
# ─────────────────────────────────────────────

async def main():
    print("=" * 60)
    print(f"🔮 Zen Tarot 监控启动 @ {now_bj_str()}")
    print(f"   SUPABASE_KEY 来源: {'环境变量' if os.environ.get('SUPABASE_KEY') else 'hardcode fallback'}")
    print("=" * 60)

    print("\n[Step 1] 抓取 Threads...")
    threads_data = await scrape_threads()

    print("\n[Step 2] 查询 Supabase...")
    supabase_data = query_supabase()

    print("\n[Step 3] 发送飞书通知...")
    send_feishu(threads_data, supabase_data)

    print("\n✅ 完成！")


if __name__ == "__main__":
    asyncio.run(main())
