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
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    today_bj = datetime.now(BEIJING_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    today_utc = today_bj.astimezone(timezone.utc).isoformat()
    
    res = supabase.table("tarot_history").select("anonymous_id").gte("created_at", today_utc).execute()
    data = res.data or []
    total_flips = len(data)
    uv = len(set(row['anonymous_id'] for row in data))
    
    q_res = supabase.table("tarot_history").select("question, created_at").not_.is_("question", "null").order("created_at", desc=True).limit(200).execute()
    seen, qs = set(), []
    for row in (q_res.data or []):
        q = (row['question'] or "").strip()
        if len(q) > 2 and q not in seen:
            seen.add(q)
            utc_dt = datetime.fromisoformat(row['created_at'].replace('Z', '+00:00'))
            bj_time = utc_dt.astimezone(BEIJING_TZ).strftime("%H:%M")
            qs.append(f"[{bj_time}] {q}")
        if len(qs) >= 20: break
    return uv, total_flips, qs

def push_feishu(uv, flips, qs):
    q_text = "\n".join(qs) if qs else "今日暂无提问"
    now_str = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M")
    payload = {
        "msg_type": "interactive",
        "card": {
            "header": {"title": {"tag": "plain_text", "content": "🔮 Zen Tarot 运营速报"}, "template": "purple"},
            "elements": [
                {"tag": "markdown", "content": f"**📊 今日数据**\n👤 UV：**{uv}**\n🃏 翻牌总数：**{flips}**\n🕒 时间：{now_str}"},
                {"tag": "hr"},
                {"tag": "markdown", "content": f"**❓ 最新提问**\n{q_text}"}
            ]
        }
    }
    r = requests.post(FEISHU_WEBHOOK, json=payload)
    print(f"飞书返回: {r.text}")

if __name__ == "__main__":
    if SUPABASE_KEY:
        uv_val, flips_val, qs_val = get_stats()
        push_feishu(uv_val, flips_val, qs_val)
