import os
import requests
from datetime import datetime, timezone, timedelta
from supabase import create_client, Client

# --- 配置 ---
SUPABASE_URL = "https://ybragvmvirddqfotqxig.supabase.co"
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/db9c21f0-9453-410d-ae0e-c9116a8dc612"
BEIJING_TZ = timezone(timedelta(hours=8))

def get_final_stats():
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    # --- 核心：手动强制锁定北京时间 4月6日的 UTC 范围 ---
    # 北京时间 4/6 00:00 = UTC时间 4/5 16:00
    # 北京时间 4/6 23:59 = UTC时间 4/6 15:59
    start_utc = "2026-04-05T16:00:00.000Z"
    end_utc = "2026-04-06T15:59:59.999Z"
    
    print(f"--- 正在提取 UTC 范围: {start_utc} 至 {end_utc} ---")

    # 1. 抓取总次数 (Exact Count)
    res_count = supabase.table("tarot_history")\
        .select("id", count="exact")\
        .gte("created_at", start_utc)\
        .lte("created_at", end_utc)\
        .limit(1).execute()
    total_flips = res_count.count if res_count.count else 0

    # 2. 抓取独立用户 (UV) - 暴力翻页抓取所有 anonymous_id
    all_users = set()
    offset = 0
    while True:
        r = supabase.table("tarot_history")\
            .select("anonymous_id")\
            .gte("created_at", start_utc)\
            .lte("created_at", end_utc)\
            .range(offset, offset + 999).execute()
        
        if not r.data: break
        all_users.update([row['anonymous_id'] for row in r.data])
        if len(r.data) < 1000: break
        offset += 1000
    
    uv = len(all_users)

    # 3. 获取最新提问
    q_res = supabase.table("tarot_history")\
        .select("question")\
        .not_.is_("question", "null")\
        .order("created_at", desc=True)\
        .limit(30).execute()
    
    qs = []
    seen = set()
    for row in (q_res.data or []):
        q = (row['question'] or "").strip()
        if len(q) > 2 and q not in seen:
            seen.add(q)
            qs.append(f"· {q}")
        if len(qs) >= 10: break
            
    return uv, total_flips, qs

def push_to_feishu(uv, flips, qs):
    # 纯文本发送，杜绝一切格式错误
    message = (
        f"🔮 **Zen Tarot 运营简报**\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📅 统计日期：2026-04-06\n"
        f"👤 独立用户 (UV)：**{uv}**\n"
        f"🃏 占卜总次数：**{flips}**\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"❓ **最新提问：**\n" + "\n".join(qs) + "\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⏰ 更新时间：{datetime.now(BEIJING_TZ).strftime('%H:%M')}"
    )

    payload = {"msg_type": "text", "content": {"text": message}}
    requests.post(FEISHU_WEBHOOK, json=payload, timeout=10)

if __name__ == "__main__":
    try:
        u, f, q = get_final_stats()
        push_to_feishu(u, f, q)
    except Exception as e:
        print(f"报错: {e}")
