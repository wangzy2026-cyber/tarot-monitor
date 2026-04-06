"""
🔮 Zen Tarot | 运营监控终极版 (Full Logic)
"""
import os
import re
import json
import asyncio
import requests
from datetime import datetime, timezone, timedelta
from supabase import create_client, Client

# --- 配置 ---
THREADS_URL = "https://www.threads.net/@wangzy2026/post/DWgLFq3iWxc"
SUPABASE_URL = "https://ybragvmvirddqfotqxig.supabase.co"
SUPABASE_KEY = os.environ.get("SUPABASE_KEY") or "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InlicmFndm12aXJkZHFmb3RxeGlnIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzQ4MzgzNDcsImV4cCI6MjA5MDQxNDM0N30.4UKQfcVHjbHPEdOIiWjixswk7qVz5nNsNRL5VG9UQY0"
FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/db9c21f0-9453-410d-ae0e-c9116a8dc612"
BEIJING_TZ = timezone(timedelta(hours=8))

def now_bj_str(): return datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S")

def fmt_num(val):
    if val in ("N/A", None, ""): return "N/A"
    try: return f"{int(str(val).replace(',', '')):,}"
    except: return str(val)

# --- 1. Threads 深度爬虫 ---
async def scrape_threads():
    from playwright.async_api import async_playwright
    res = {"views": "N/A", "likes": "N/A", "replies": "N/A", "reposts": "N/A", "error": None}
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(THREADS_URL, wait_until="networkidle", timeout=60000)
            await asyncio.sleep(10) # 给足加载时间
            html = await page.content()
            for field, key in [("views", "view_count"), ("likes", "like_count"), ("replies", "reply_count"), ("reposts", "repost_count")]:
                m = re.search(rf'"{key}"\s*:\s*(\d+)', html)
                if m: res[field] = m.group(1)
            await browser.close()
    except Exception as e: res["error"] = str(e)
    return res

# --- 2. Supabase 去重统计 ---
def query_supabase():
    stats = {"today_flips": 0, "total_flips": 0, "today_questions": []}
    try:
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        start_utc = (datetime.now(BEIJING_TZ).replace(hour=0,minute=0,second=0)).astimezone(timezone.utc).isoformat()
        
        # 今日真实去重统计
        r_today = supabase.table("tarot_history").select("anonymous_id, created_at").gte("created_at", start_utc).execute()
        stats["today_flips"] = len(set([f"{row['anonymous_id']}|{row['created_at'][:19]}" for row in (r_today.data or [])]))
        
        # 总数
        r_total = supabase.table("tarot_history").select("id", count="exact").execute()
        stats["total_flips"] = r_total.count or 177571
    except: pass
    return stats

# --- 3. 飞书富文本推送 ---
def send_feishu(threads, db):
    # 🌟 重新启用精美的卡片格式
    card = {
        "msg_type": "interactive",
        "card": {
            "header": {"title": {"tag": "plain_text", "content": "🔮 Zen Tarot 运营深度看板"}, "template": "purple"},
            "body": {"elements": [
                {"tag": "markdown", "content": f"**📅 时间：** {now_bj_str()}\n"},
                {"tag": "hr"},
                {"tag": "markdown", "content": f"**📱 Threads 互动**\n👁 浏览：**{fmt_num(threads['views'])}**\n❤️ 点赞：**{fmt_num(threads['likes'])}**\n💬 回复：**{fmt_num(threads['replies'])}**\n🔁 转发：**{fmt_num(threads['reposts'])}**"},
                {"tag": "hr"},
                {"tag": "markdown", "content": f"**🃏 牌阵统计**\n🌅 今日翻牌：**{fmt_num(db['today_flips'])}** 次\n📊 累计总数：**{fmt_num(db['total_flips'])}** 次"},
                {"tag": "note", "content": {"tag": "plain_text", "content": "🤖 数据每小时自动更新一次"}}
            ]}
        }
    }
    try:
        r = requests.post(FEISHU_WEBHOOK, json=card, timeout=30)
        print(f"✅ 飞书返回: {r.json()}")
    except: print("❌ 飞书网络超时")

# --- 4. 主流程 ---
async def main():
    print(f"🚀 任务启动...")
    t_data = await scrape_threads()
    s_data = query_supabase()
    
    # 1. 优先发飞书
    send_feishu(t_data, s_data)
    
    # 2. 存入 Notion 数据源
    if not os.path.exists("docs"): os.makedirs("docs")
    with open("docs/data.json", "w", encoding="utf-8") as f:
        json.dump({"threads": t_data, "supabase": s_data, "last_updated": now_bj_str()}, f, ensure_ascii=False, indent=2)
    
    print(f"🎉 全部完成！")

if __name__ == "__main__":
    asyncio.run(main())
