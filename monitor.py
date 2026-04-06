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
    print("--- 正在提取数据 ---")
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    # 1. 统计今日 UV/次数 (北京时间 0 点起)
    today_bj = datetime.now(BEIJING_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    start_time_utc = today_bj.astimezone(timezone.utc).isoformat()
    
    res = supabase.table("tarot_history").select("anonymous_id").gte("created_at", start_time_utc).execute()
    data = res.data or []
    total_flips = len(data)
    uv = len(set(row['anonymous_id'] for row in data))
    
    # 2. 提取最新去重提问
    q_res = supabase.table("tarot_history").select("question, created_at").not_.is_("question", "null").order("created_at", desc=True).limit(100).execute()
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
    print("--- 正在推送飞书 ---")
    now_str = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M")
    q_text = "\n".join(qs) if qs else "今日暂无提问"

    # 飞书交互式卡片 JSON 结构 (严格校对版)
    payload = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": "🔮 Zen Tarot 运营看板"},
                "template": "purple"
            },
            "elements": [
                {
                    "tag": "markdown",
                    "content": f"**📊 今日实时数据 (0点起)**\n👤 UV：**{uv}**\n🃏 翻牌总数：**{flips}**\n🕒 时间：{now_str}"
                },
                {"tag": "hr"},
                {
                    "tag": "markdown",
                    "content": f"**❓ 最新提问 (Top 20)**\n{q_text}"
                }
            ]
        }
    }
    
    # 使用 json= 参数发送，requests 会自动设置 Content-Type: application/json
    r = requests.post(FEISHU_WEBHOOK, json=payload, timeout=15)
    print(f"飞书 API 返回: {r.text}")

if __name__ == "__main__":
    try:
        u, f, q = get_stats()
        push_feishu(u, f, q)
    except Exception as e:
        print(f"❌ 程序报错: {e}")
