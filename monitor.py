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
    
    # 精准计算北京时间今日 0 点对应的 UTC 时间
    now_bj = datetime.now(BEIJING_TZ)
    today_0am_bj = now_bj.replace(hour=0, minute=0, second=0, microsecond=0)
    start_time_utc = today_0am_bj.astimezone(timezone.utc).isoformat()

    # 1. 统计 UV 和 翻牌次数
    res = supabase.table("tarot_history").select("anonymous_id").gte("created_at", start_time_utc).execute()
    data = res.data or []
    total_flips = len(data)
    uv = len(set(row['anonymous_id'] for row in data))
    
    # 2. 提取最新 20 条提问 (去重)
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
    q_text = "\n".join(qs) if qs else "今日暂无提问"
    now_str = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M")

    # 构建结构化卡片（直接用 Dict，不手动拼字符串）
    card_payload = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": "🔮 Zen Tarot 运营速报"},
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
                    "content": f"**❓ 最新提问**\n{q_text}"
                }
            ]
        }
    }
    
    # 核心修复点：使用 json=card_payload，requests 会自动完成安全转义
    r = requests.post(FEISHU_WEBHOOK, json=card_payload, timeout=10)
    print(f"飞书 API 返回: {r.text}")

if __name__ == "__main__":
    try:
        uv_val, flips_val, qs_val = get_stats()
        push_feishu(uv_val, flips_val, qs_val)
    except Exception as e:
        print(f"❌ 程序报错: {e}")
