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
    print(f"正在连接 Supabase...")
    if not SUPABASE_KEY:
        raise ValueError("环境变量 SUPABASE_KEY 为空，请检查 GitHub Secrets 配置！")
    
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    # 逻辑 A：今日数据
    today_bj = datetime.now(BEIJING_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    today_utc = today_bj.astimezone(timezone.utc).isoformat()
    print(f"查询今日数据 (UTC 起始时间: {today_utc})...")
    
    res = supabase.table("tarot_history").select("anonymous_id").gte("created_at", today_utc).execute()
    data = res.data or []
    total_flips = len(data)
    uv = len(set(row['anonymous_id'] for row in data))
    print(f"今日结果: UV={uv}, 次数={total_flips}")
    
    # 逻辑 B：最新提问
    print("查询最新提问...")
    q_res = supabase.table("tarot_history")\
        .select("question, created_at")\
        .not_.is_("question", "null")\
        .order("created_at", desc=True)\
        .limit(200).execute()
    
    seen = set()
    qs = []
    for row in (q_res.data or []):
        q = row['question'].strip()
        if len(q) > 2 and q not in seen:
            seen.add(q)
            utc_dt = datetime.fromisoformat(row['created_at'].replace('Z', '+00:00'))
            bj_time = utc_dt.astimezone(BEIJING_TZ).strftime("%H:%M")
            qs.append(f"[{bj_time}] {q}")
        if len(qs) >= 100: break
    
    return uv, total_flips, qs

def push_feishu(uv, flips, qs):
    print(f"正在推送至飞书 Webhook...")
    q_display = "\n".join(qs[:15]) + (f"\n...等共 {len(qs)} 条" if len(qs) > 15 else "")
    now_str = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M")
    
    card = {
        "msg_type": "interactive",
        "card": {
            "header": {"title": {"tag": "plain_text", "content": "🔮 Zen Tarot 运营速报"}, "template": "purple"},
            "body": {"elements": [
                {"tag": "markdown", "content": f"**📊 今日实时数据**\n👤 独立用户 (UV)：**{uv}**\n🃏 翻牌总次数：**{flips}**\n🕒 统计时间：{now_str}"},
                {"tag": "hr"},
                {"tag": "markdown", "content": f"**❓ 最新用户提问 (去重)**\n{q_display or '暂无提问'}"}
            ]}
        }
    }
    r = requests.post(FEISHU_WEBHOOK, json=card)
    print(f"飞书返回状态码: {r.status_code}")
    print(f"飞书返回内容: {r.text}")

if __name__ == "__main__":
    uv, flips, qs = get_stats()
    push_feishu(uv, flips, qs)
