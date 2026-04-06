import os
import re
import json
import asyncio
import requests
from datetime import datetime, timezone, timedelta
from supabase import create_client, Client

# ─────────────────────────────────────────────
# 1. 配置信息
# ─────────────────────────────────────────────
THREADS_URL = "https://www.threads.net/@wangzy2026/post/DWgLFq3iWxc"
SUPABASE_URL = "https://ybragvmvirddqfotqxig.supabase.co"
SUPABASE_KEY = os.environ.get("SUPABASE_KEY") or "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InlicmFndm12aXJkZHFmb3RxeGlnIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzQ4MzgzNDcsImV4cCI6MjA5MDQxNDM0N30.4UKQfcVHjbHPEdOIiWjixswk7qVz5nNsNRL5VG9UQY0"
BEIJING_TZ = timezone(timedelta(hours=8))

def now_bj_str():
    return datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S")

# ─────────────────────────────────────────────
# 2. 核心逻辑
# ─────────────────────────────────────────────

async def scrape_threads():
    from playwright.async_api import async_playwright
    res = {"views": "N/A", "likes": "N/A", "replies": "N/A", "error": None}
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(THREADS_URL, wait_until="networkidle", timeout=60000)
            html = await page.content()
            # 匹配指标
            for field, key in [("views", "view_count"), ("likes", "like_count"), ("replies", "reply_count")]:
                m = re.search(rf'"{key}"\s*:\s*(\d+)', html)
                if m: res[field] = m.group(1)
            await browser.close()
    except Exception as e: res["error"] = str(e)
    return res

def query_supabase():
    stats = {"today_flips": 0, "total_flips": 0}
    try:
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        # 今日翻牌 (北京时间 0 点起)
        start_utc = (datetime.now(BEIJING_TZ).replace(hour=0,minute=0,second=0)).astimezone(timezone.utc).isoformat()
        r_today = supabase.table("tarot_history").select("id", count="exact").gte("created_at", start_utc).execute()
        stats["today_flips"] = r_today.count or 0
        # 总数
        r_total = supabase.table("tarot_history").select("id", count="exact").execute()
        stats["total_flips"] = r_total.count or 163000
    except: pass
    return stats

async def main():
    print(f"🚀 开始执行任务: {now_bj_str()}")
    
    threads = await scrape_threads()
    db = query_supabase()
    
    # 🌟 关键：保存到 docs 文件夹
    payload = {
        "threads": threads,
        "supabase": db,
        "last_updated": now_bj_str()
    }
    
    if not os.path.exists("docs"): os.makedirs("docs")
    with open("docs/data.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    
    print(f"✅ 数据已写入 docs/data.json")

if __name__ == "__main__":
    asyncio.run(main())
