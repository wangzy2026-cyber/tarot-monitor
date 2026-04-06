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
    print("正在连接 Supabase...")
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    today_bj = datetime.now(BEIJING_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    today_utc = today_bj.astimezone(timezone.utc).isoformat()
    
    # 1. UV/次数
    res = supabase.table("tarot_history").select("anonymous_id").gte("created_at", today_utc).execute()
    data = res.data or []
    total_flips = len(data)
    uv = len(set(row['anonymous_id'] for row in data))
    
    # 2. 最新提问 (去重)
    q_res = supabase.table("tarot_history")\
        .select("question, created_at")\
        .not_.is_("question", "null")\
        .order("created_at", desc=True)\
        .limit(200).execute()
    
    seen = set()
    qs = []
    for row in (q_res.data or []):
        q = (row['question'] or "").strip()
        if len(q) > 2 and q not in seen:
            seen.add(q)
            # 格式化时间
            utc_dt = datetime.fromisoformat(row['created_at'].replace('Z', '+00:00'))
            bj_time = utc_dt.astimezone(BEIJING_TZ).strftime("%H:%M")
            qs.append(f"[{bj_time}] {q}")
        if len(qs) >= 50: break # 飞书卡片有长度限制，50条够看了
    
    return uv, total_flips, qs

def push_feishu(uv, flips, qs):
    print("正在构建安全卡片并推送到飞书...")
    # 使用 \n 拼接，并在后面统一交给 json.dumps 处理
    q_text = "\n".join(qs[:20]) # 先取前20条显示，防止消息过长被飞书截断
    if len(qs) > 20:
        q_text += f"\n...今日共有 {len(qs)} 条去重提问"

    now_str = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M")
    
    # 构建结构化的卡片
    card_content = {
        "config": {"wide_screen_mode": True},
        "header": {"title": {"tag": "plain_text", "content": "🔮 Zen Tarot 运营简报"}, "template": "purple"},
        "elements": [
            {"tag": "markdown", "content": f"**📅 统计时间：** {now_str}"},
            {"tag": "hr"},
            {"tag": "markdown", "content": f"**📊 今日实时数据**\n👤 UV：**{uv}**\n🃏 翻牌总数：**{flips}**"},
            {"tag": "hr"},
            {"tag": "markdown", "content": f"**❓ 最新提问 (Top 20)**\n{q_text}"}
        ]
    }
    
    payload = {
        "msg_type": "interactive",
        "card": card_content
    }
    
    # 重点：必须用 json=payload，requests 会自动处理转义
    r = requests.post(FEISHU_WEBHOOK, json=payload)
    print(f"飞书返回内容: {r.text}")

if __name__ == "__main__":
    try:
        uv_val, flips_val, qs_val = get_stats()
        push_feishu(uv_val, flips_val, qs_val)
    except Exception as e:
        print(f"程序崩了: {e}")
