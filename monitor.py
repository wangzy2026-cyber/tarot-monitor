"""
🔮 Zen Tarot 塔罗项目 · 自动化运营监控脚本
功能：抓取 Threads 数据 + Supabase 统计 + 飞书通知
"""

import os
import re
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
SUPABASE_KEY = os.environ.get(
    "SUPABASE_KEY",
    "sb_publishable_Kf3_0KgYnDX62_Tk6QbrBA_3zeEIjm9"
)

FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/db9c21f0-9453-410d-ae0e-c9116a8dc612"

BEIJING_TZ = timezone(timedelta(hours=8))

# ─────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────

def beijing_today_utc_range():
    """返回北京时间今日 00:00 ~ 明日 00:00 对应的 UTC 时间戳字符串（ISO 格式）"""
    now_bj = datetime.now(BEIJING_TZ)
    start_bj = now_bj.replace(hour=0, minute=0, second=0, microsecond=0)
    end_bj   = start_bj + timedelta(days=1)
    start_utc = start_bj.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    end_utc   = end_bj.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    return start_utc, end_utc


def now_bj_str():
    return datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S")


# ─────────────────────────────────────────────
# 1. Threads 数据抓取（Playwright）
# ─────────────────────────────────────────────

async def scrape_threads() -> dict:
    """使用 Playwright headless Chromium 抓取 Threads 帖子数据"""
    from playwright.async_api import async_playwright

    result = {
        "views": "N/A",
        "likes": "N/A",
        "reposts": "N/A",
        "replies": "N/A",
        "comments": [],
        "error": None,
    }

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
            ],
        )

        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            locale="zh-CN",
        )

        page = await context.new_page()

        # 屏蔽图片/媒体加速加载
        await page.route("**/*.{png,jpg,jpeg,gif,webp,mp4,webm}", lambda route: route.abort())

        try:
            print(f"[Threads] 正在访问: {THREADS_URL}")
            await page.goto(THREADS_URL, wait_until="domcontentloaded", timeout=60000)

            # 随机等待 3~7 秒，模拟真人阅读
            wait_sec = random.uniform(3, 7)
            print(f"[Threads] 随机等待 {wait_sec:.1f}s ...")
            await asyncio.sleep(wait_sec)

            # 再次随机滚动，触发懒加载
            await page.evaluate("window.scrollBy(0, Math.random() * 600 + 200)")
            await asyncio.sleep(random.uniform(1.5, 3.0))

            html = await page.content()

            # ── 解析指标 ──────────────────────────────
            # Views
            views_match = re.search(r'([\d,\.]+[KMB]?)\s*(?:views|浏览)', html, re.IGNORECASE)
            if views_match:
                result["views"] = views_match.group(1)

            # Likes
            likes_match = re.search(r'"likeCount"\s*:\s*(\d+)', html)
            if not likes_match:
                likes_match = re.search(r'([\d,\.]+[KMB]?)\s*(?:likes?|赞)', html, re.IGNORECASE)
            if likes_match:
                result["likes"] = likes_match.group(1)

            # Reposts
            reposts_match = re.search(r'"repostCount"\s*:\s*(\d+)', html)
            if not reposts_match:
                reposts_match = re.search(r'([\d,\.]+[KMB]?)\s*(?:reposts?|转发)', html, re.IGNORECASE)
            if reposts_match:
                result["reposts"] = reposts_match.group(1)

            # Replies
            replies_match = re.search(r'"replyCount"\s*:\s*(\d+)', html)
            if not replies_match:
                replies_match = re.search(r'([\d,\.]+[KMB]?)\s*(?:repl(?:y|ies)|回复)', html, re.IGNORECASE)
            if replies_match:
                result["replies"] = replies_match.group(1)

            # ── 抓取最新 10 条评论 ────────────────────
            # 尝试定位评论区文本节点
            comment_nodes = await page.query_selector_all(
                'div[data-pressable-container] span, '
                'article span[dir="auto"], '
                '[role="article"] p'
            )
            seen = set()
            comments = []
            for node in comment_nodes:
                text = (await node.inner_text()).strip()
                # 过滤：长度在 5~500 之间、非重复
                if 5 <= len(text) <= 500 and text not in seen:
                    seen.add(text)
                    comments.append(text)
                if len(comments) >= 10:
                    break
            result["comments"] = comments

            print(f"[Threads] 抓取完成：views={result['views']}, likes={result['likes']}, "
                  f"reposts={result['reposts']}, replies={result['replies']}, "
                  f"comments={len(result['comments'])}条")

        except Exception as e:
            result["error"] = str(e)
            print(f"[Threads] 抓取异常: {e}")
        finally:
            await context.close()
            await browser.close()

    return result


# ─────────────────────────────────────────────
# 2. Supabase 数据统计
# ─────────────────────────────────────────────

def query_supabase() -> dict:
    """查询 Supabase，统计北京时间今日数据"""
    stats = {
        "today_flips": 0,
        "total_flips": 0,
        "today_questions": [],
        "error": None,
    }

    try:
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        start_utc, end_utc = beijing_today_utc_range()

        print(f"[Supabase] 今日北京时间范围 (UTC): {start_utc} ~ {end_utc}")

        # ── 今日真实翻牌数（去重）────────────────────
        # 使用 RPC 或 raw SQL；这里用 postgrest 的 select + filter 近似
        # 注意：Supabase Python SDK 暂不支持 DISTINCT 聚合，改用 RPC
        try:
            today_resp = supabase.rpc(
                "count_today_flips",
                {"start_utc": start_utc, "end_utc": end_utc}
            ).execute()
            stats["today_flips"] = today_resp.data if isinstance(today_resp.data, int) else 0
        except Exception:
            # fallback：直接 count（可能含重复）
            today_resp = (
                supabase.table("readings")
                .select("id", count="exact")
                .gte("created_at", start_utc)
                .lt("created_at", end_utc)
                .execute()
            )
            stats["today_flips"] = today_resp.count or 0

        # ── 总翻牌数（全量去重）──────────────────────
        try:
            total_resp = supabase.rpc("count_total_flips", {}).execute()
            stats["total_flips"] = total_resp.data if isinstance(total_resp.data, int) else 0
        except Exception:
            total_resp = (
                supabase.table("readings")
                .select("id", count="exact")
                .execute()
            )
            stats["total_flips"] = total_resp.count or 0

        # ── 今日最新 100 条真实问题（去重）────────────
        try:
            q_resp = (
                supabase.table("readings")
                .select("question, created_at")
                .gte("created_at", start_utc)
                .lt("created_at", end_utc)
                .not_.is_("question", "null")
                .order("created_at", desc=True)
                .limit(200)
                .execute()
            )
            seen_q = set()
            unique_questions = []
            for row in (q_resp.data or []):
                q = (row.get("question") or "").strip()
                if q and q not in seen_q:
                    seen_q.add(q)
                    unique_questions.append(q)
                if len(unique_questions) >= 100:
                    break
            stats["today_questions"] = unique_questions
        except Exception as e:
            print(f"[Supabase] 问题抓取异常: {e}")

        print(f"[Supabase] 今日翻牌={stats['today_flips']}, 总翻牌={stats['total_flips']}, "
              f"今日问题={len(stats['today_questions'])}条")

    except Exception as e:
        stats["error"] = str(e)
        print(f"[Supabase] 连接异常: {e}")

    return stats


# ─────────────────────────────────────────────
# 3. 飞书富文本卡片通知
# ─────────────────────────────────────────────

def send_feishu(threads_data: dict, supabase_data: dict):
    """发送飞书富文本卡片消息"""

    run_time = now_bj_str()

    # 构建评论列表文本
    comments_text = ""
    if threads_data.get("comments"):
        for i, c in enumerate(threads_data["comments"][:10], 1):
            comments_text += f"{i}. {c[:80]}{'…' if len(c)>80 else ''}\n"
    else:
        comments_text = "（暂无评论数据）"

    # 构建问题列表文本（取前 20 条展示）
    questions_text = ""
    questions = supabase_data.get("today_questions", [])
    if questions:
        for i, q in enumerate(questions[:20], 1):
            questions_text += f"{i}. {q[:60]}{'…' if len(q)>60 else ''}\n"
        if len(questions) > 20:
            questions_text += f"… 共 {len(questions)} 条（展示前 20 条）\n"
    else:
        questions_text = "（今日暂无问题）"

    threads_error_tip = f"\n⚠️ 抓取异常：{threads_data['error']}" if threads_data.get("error") else ""
    supabase_error_tip = f"\n⚠️ 数据库异常：{supabase_data['error']}" if supabase_data.get("error") else ""

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
                "template": "purple"
            },
            "body": {
                "elements": [
                    # 运行时间
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
                            f"👁️ 浏览量：**{threads_data['views']}**　"
                            f"❤️ 点赞：**{threads_data['likes']}**　"
                            f"🔁 转发：**{threads_data['reposts']}**　"
                            f"💬 回复：**{threads_data['replies']}**"
                            f"{threads_error_tip}"
                        )
                    },
                    {"tag": "hr"},

                    # 最新评论
                    {
                        "tag": "markdown",
                        "content": f"**💬 最新 10 条评论**\n{comments_text}"
                    },
                    {"tag": "hr"},

                    # Supabase 翻牌统计
                    {
                        "tag": "markdown",
                        "content": (
                            "**🗃️ 翻牌数据统计**\n"
                            f"🌅 今日翻牌（北京时间）：**{supabase_data['today_flips']}** 次\n"
                            f"📊 累计总翻牌：**{supabase_data['total_flips']}** 次"
                            f"{supabase_error_tip}"
                        )
                    },
                    {"tag": "hr"},

                    # 今日问题
                    {
                        "tag": "markdown",
                        "content": f"**❓ 今日用户提问（去重后共 {len(questions)} 条）**\n{questions_text}"
                    },
                    {"tag": "hr"},

                    # 底部
                    {
                        "tag": "markdown",
                        "content": "🤖 *由 GitHub Actions 定时触发 · Zen Tarot 运营机器人*"
                    }
                ]
            }
        }
    }

    try:
        resp = requests.post(FEISHU_WEBHOOK, json=card, timeout=15)
        resp.raise_for_status()
        result = resp.json()
        if result.get("code") == 0:
            print(f"[飞书] 消息发送成功 ✅")
        else:
            print(f"[飞书] 发送失败: {result}")
    except Exception as e:
        print(f"[飞书] 发送异常: {e}")


# ─────────────────────────────────────────────
# 主函数
# ─────────────────────────────────────────────

async def main():
    print("=" * 60)
    print(f"🔮 Zen Tarot 监控启动 @ {now_bj_str()}")
    print("=" * 60)

    # Step 1: 抓取 Threads
    print("\n[Step 1] 抓取 Threads 数据...")
    threads_data = await scrape_threads()

    # Step 2: 查询 Supabase
    print("\n[Step 2] 查询 Supabase 数据...")
    supabase_data = query_supabase()

    # Step 3: 发送飞书通知
    print("\n[Step 3] 发送飞书通知...")
    send_feishu(threads_data, supabase_data)

    print("\n✅ 监控任务完成！")


if __name__ == "__main__":
    asyncio.run(main())
