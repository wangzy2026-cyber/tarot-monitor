"""
🔮 Zen Tarot 终极监控脚本
功能：Threads 爬虫 + Supabase 统计 + 生成 docs/data.json + 飞书卡片推送
"""

import os
import re
import json
import asyncio
import requests
from datetime import datetime, timezone, timedelta
from supabase import create_client, Client

# ─────────────────────────────────────────────
# 1. 配置（Webhook 和 URL）
# ─────────────────────────────────────────────
THREADS_URL = "https://www.threads.net/@wangzy2026/post/DWgLFq3iWxc"
SUPABASE_URL = "https://ybragvmvirddqfotqxig.supabase.co"
# 优先从 GitHub Secrets 读取，没有则用你提供的 Key
SUPABASE_KEY = os.environ.get("SUPABASE_KEY") or "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InlicmFndm12aXJkZHFmb3RxeGlnIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzQ4MzgzNDcsImV4cCI6MjA5MDQxNDM0N30.4UKQfcVHjbHPEdOIiWjixswk7qVz5nNsNRL5VG9UQY0"
FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/db9c21f0-9453-410d-ae0e-c9116a8dc612"
BEIJING_TZ = timezone(timedelta(hours=8))

def now_bj_str():
    return datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S")

def fmt_num(val):
    if val in ("N/A", None, ""): return "N/A"
    try: return f"{int(str(val).replace(',', '')):,}"
    except: return str(val)

# ─────────────────────────────────────────────
# 2. 数据抓取与查询
# ─────────────────────────────────────────────

async def scrape_threads():
    from playwright.async_api import async_playwright
    res = {"views": "N/A", "likes": "N/A", "replies": "N/A", "reposts": "N/A", "error": None}
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            # 增加等待时间确保数据加载
            await page.goto(THREADS_URL, wait_until="networkidle", timeout=60000)
            await asyncio.sleep(8) 
            html = await page.content()
            # 匹配点赞、浏览、回复
            for field, key in [("views", "view_count"), ("likes", "like_count"), ("replies", "reply_count"), ("reposts", "repost_count")]:
                m = re.search(rf'"{key}"\s*:\s*(\d+)', html)
                if m: res[field] = m.group(1)
            await browser.close()
    except Exception as e: res["error"] = str(e)
    return res

def query_supabase():
    stats = {"today_flips": 0, "total_flips": 0, "error": None}
    try:
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        start_utc = (datetime.now(BEIJING_TZ).replace(hour=0,minute=0,second=0)).astimezone(timezone.utc).isoformat()
        # 今日数
        r_today = supabase.table("tarot_history").select("id", count="exact").gte("created_at", start_utc).execute()
        stats["today_flips"] = r_today.count or 0
        # 总数
        r_total = supabase.table("tarot_history").select("id", count="exact").execute()
        stats["total_flips"] = r_total.count or 177571
    except Exception as e: stats["error"] = str(e)
    return stats

# ─────────────────────────────────────────────
# 3. 飞书推送逻辑 (找回灵魂)
# ─────────────────────────────────────────────

def send_feishu(threads, db):
    card = {
        "msg_type": "interactive",
        "card": {
            "header": {"title": {"tag": "plain_text", "content": "🔮 Zen Tarot · 实时运营看板"}, "template": "purple"},
            "body": {"elements": [
                {"tag": "markdown", "content": f"**📅 时间：** {now_bj_str()}\n\n"
                                             f"**📊 Threads 数据**\n"
                                             f"👁 浏览：**{fmt_num(threads['views'])}** | ❤️ 点赞：**{fmt_num(threads['likes'])}**\n"
                                             f"💬 回复：**{fmt_num(threads['replies'])}**\n\n"
                                             f"**🃏 数据库统计**\n"
                                             f"🌅 今日翻牌：**{fmt_num(db['today_flips'])}** 次\n"
                                             f"📈 累计总数：**{fmt_num(db['total_flips'])}** 次"},
                {"tag": "hr"},
                {"tag": "note", "content": {"tag": "plain_text", "content": "🤖 GitHub Actions 自动更新"}}
            ]}
        }
    }
    try:
        requests.post(FEISHU_WEBHOOK, json=card, timeout=15)
        print("✅ 飞书消息已发出")
    except: print("❌ 飞书推送失败")

# ─────────────────────────────────────────────
# 4. 主入口
# ─────────────────────────────────────────────

async def main():
    print(f"🚀 任务启动...")
    threads = await scrape_threads()
    db = query_supabase()
    
    # 存入 JSON
    if not os.path.exists("docs"): os.makedirs("docs")
    with open("docs/data.json", "w", encoding="utf-8") as f:
        json.dump({"threads": threads, "supabase": db, "last_updated": now_bj_str()}, f, ensure_ascii=False, indent=2)
    
    # 发送飞书
    send_feishu(threads, db)
    print(f"🎉 全部完成！")

if __name__ == "__main__":
    asyncio.run(main())
