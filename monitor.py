import os
import requests
import json
from datetime import datetime, timezone, timedelta
from supabase import create_client, Client

# --- 配置 ---
SUPABASE_URL = "https://ybragvmvirddqfotqxig.supabase.co"
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/db9c21f0-9453-410d-ae0e-c9116a8dc612"
BEIJING_TZ = timezone(timedelta(hours=8))

def get_stats():
    print("--- 正在使用 SQL 逻辑提取精准数据 ---")
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    # 1. 严格计算北京时间今日 0 点 (对应 UTC 前一天 16:00)
    today_bj_start = datetime.now(BEIJING_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    utc_start = today_bj_start.astimezone(timezone.utc).isoformat()
    
    # --- 核心：直接用 CountExact 拿到总数 (对应 SQL: COUNT(*)) ---
    count_res = supabase.table("tarot_history")\
        .select("id", count="exact")\
        .gte("created_at", utc_start)\
        .limit(1).execute()
    total_flips = count_res.count if count_res.count else 0

    # --- 核心：解决 UV 翻倍问题 (对应 SQL: COUNT(DISTINCT anonymous_id)) ---
    # 之前翻倍是因为拉取了重复数据。现在我们分批拉取 ID 并彻底去重。
    unique_users = set()
    last_id = 0 # 使用 ID 游标，确保不漏不重
    while True:
        r = supabase.table("tarot_history")\
            .select("id, anonymous_id")\
            .gte("created_at", utc_start)\
            .gt("id", last_id)\
            .order("id")\
            .limit(1000).execute()
        
        batch = r.data or []
        if not batch: break
        
        for row in batch:
            unique_users.add(row['anonymous_id'])
            last_id = row['id']
            
        if len(batch) < 1000: break
    
    uv = len(unique_users)
    print(f"✅ 最终核对：UV={uv}, Flips={total_flips}")

    # --- 核心：最新提问 (截断防止飞书报错) ---
    q_res = supabase.table("tarot_history")\
        .select("question, created_at")\
        .not_.is_("question", "null")\
        .order("created_at", desc=True)\
        .limit(50).execute()
    
    qs = []
    seen = set()
    for row in (q_res.data or []):
        q = (row['question'] or "").strip()
        if len(q) > 2 and q not in seen:
            seen.add(q)
            utc_dt = datetime.fromisoformat(row['created_at'].replace('Z', '+00:00'))
            bj_time = utc_dt.astimezone(BEIJING_TZ).strftime("%H:%M")
            qs.append(f"• [{bj_time}] {q}")
        if len(qs) >= 15: break
            
    return uv, total_flips, qs

def push_feishu(uv, flips, qs):
    # 强制构建飞书最稳的 Payload，修复之前 200621 报错
    card = {
        "msg_type": "interactive",
        "card": {
            "header": {"title": {"tag": "plain_text", "content": "🔮 Zen Tarot 运营看板"}, "template": "purple"},
            "elements": [
                {"tag": "markdown", "content": f"**📅 统计日期：** {datetime.now(BEIJING_TZ).strftime('%Y-%m-%d')}\n👤 独立用户 (UV)：**{uv}**\n🃏 占卜总次数：**{flips:,}**"},
                {"tag": "hr"},
                {"tag": "markdown", "content": f"**❓ 最新提问 (Top 15)**\n" + ("\n".join(qs) if qs else "暂无数据")}
            ]
        }
    }
    r = requests.post(FEISHU_WEBHOOK, json=card, timeout=15)
    print(f"飞书返回: {r.text}")

if __name__ == "__main__":
    try:
        u, f, q = get_stats()
        push_feishu(u, f, q)
    except Exception as e:
        print(f"❌ 运行崩溃: {e}")
