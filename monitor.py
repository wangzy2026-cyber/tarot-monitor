import os
import requests
from datetime import datetime, timezone, timedelta
from supabase import create_client, Client

# --- 配置 ---
SUPABASE_URL = "https://ybragvmvirddqfotqxig.supabase.co"
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/db9c21f0-9453-410d-ae0e-c9116a8dc612"
BEIJING_TZ = timezone(timedelta(hours=8))

def get_stats_from_rpc():
    print("--- 正在调用 Supabase SQL 函数 ---")
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    # 1. 直接调用我们在数据库里写好的精准 SQL 函数
    rpc_res = supabase.rpc("get_daily_stats").execute()
    stats = rpc_res.data[0] if rpc_res.data else {"today_flips": 0, "today_uv": 0}
    
    flips = stats.get("today_flips", 0)
    uv = stats.get("today_uv", 0)

    # 2. 获取最新提问 (这部分逻辑不涉及复杂聚合，直接查即可)
    q_res = supabase.table("tarot_history")\
        .select("question, created_at")\
        .not_.is_("question", "null")\
        .order("created_at", desc=True)\
        .limit(100).execute()
    
    seen, qs = set(), []
    for row in (q_res.data or []):
        q = (row['question'] or "").strip().replace('"', "'")
        if len(q) > 2 and q not in seen:
            seen.add(q)
            utc_dt = datetime.fromisoformat(row['created_at'].replace('Z', '+00:00'))
            bj_time = utc_dt.astimezone(BEIJING_TZ).strftime("%H:%M")
            qs.append(f"• [{bj_time}] {q}")
        if len(qs) >= 15: break
            
    return uv, flips, qs

def push_feishu(uv, flips, qs):
    now_str = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M")
    payload = {
        "msg_type": "interactive",
        "card": {
            "header": {"title": {"tag": "plain_text", "content": "🔮 Zen Tarot 运营看板"}, "template": "purple"},
            "elements": [
                {"tag": "markdown", "content": f"**📊 今日实时数据 (SQL对齐版)**\n👤 独立用户 (UV)：**{uv}**\n🃏 占卜总次数：**{flips:,}**\n🕒 统计日期：{datetime.now(BEIJING_TZ).strftime('%Y-%m-%d')}"},
                {"tag": "hr"},
                {"tag": "markdown", "content": f"**❓ 最新提问**\n" + "\n".join(qs)},
                {"tag": "note", "content": {"tag": "plain_text", "content": f"最后更新：{now_str}"}}
            ]
        }
    }
    r = requests.post(FEISHU_WEBHOOK, json=payload, timeout=10)
    print(f"飞书返回: {r.text}")

if __name__ == "__main__":
    try:
        u, f, q = get_stats_from_rpc()
        push_feishu(u, f, q)
    except Exception as e:
        print(f"❌ 运行失败: {e}")
