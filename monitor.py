import os
import requests
from datetime import datetime, timezone, timedelta
from supabase import create_client, Client

# --- 基础配置 (从环境变量读取 Key) ---
SUPABASE_URL = "https://ybragvmvirddqfotqxig.supabase.co"
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/db9c21f0-9453-410d-ae0e-c9116a8dc612"
BEIJING_TZ = timezone(timedelta(hours=8))

def get_stats():
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    # 逻辑 A：今日聚合统计 (北京时间 0 点起)
    today_bj = datetime.now(BEIJING_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    today_utc = today_bj.astimezone(timezone.utc).isoformat()
    
    # 统计今日所有数据
    res = supabase.table("tarot_history").select("anonymous_id").gte("created_at", today_utc).execute()
    data = res.data or []
    total_flips = len(data)
    uv = len(set(row['anonymous_id'] for row in data))
    
    # 逻辑 B：最新 100 条有效提问 (去重逻辑)
    q_res = supabase.table("tarot_history")\
        .select("question, created_at")\
        .not_.is_("question", "null")\
        .order("created_at", desc=True)\
        .limit(300).execute() # 采样 300 条进行侧端去重
    
    seen_questions = set()
    latest_questions = []
    for row in (q_res.data or []):
        q = row['question'].strip()
        # 长度大于 2 且未出现过
        if len(q) > 2 and q not in seen_questions:
            seen_questions.add(q)
            # 转换显示时间为北京时间
            utc_dt = datetime.fromisoformat(row['created_at'].replace('Z', '+00:00'))
            bj_time = utc_dt.astimezone(BEIJING_TZ).strftime("%H:%M")
            latest_questions.append(f"[{bj_time}] {q}")
        if len(latest_questions) >= 100:
            break
            
    return uv, total_flips, latest_questions

def push_feishu(uv, flips, qs):
    # 飞书卡片只展示前 10 个问题预览，避免消息过长，完整列表可在多维表格看（如果需要）
    q_display = "\n".join(qs[:15]) + (f"\n...等共 {len(qs)} 条" if len(qs) > 15 else "")
    
    now_str = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M")
    
    card = {
        "msg_type": "interactive",
        "card": {
            "header": {"title": {"tag": "plain_text", "content": "🔮 Zen Tarot 运营速报"}, "template": "purple"},
            "body": {"elements": [
                {"tag": "markdown", "content": f"**📅 统计时间：** {now_str}"},
                {"tag": "hr"},
                {"tag": "markdown", "content": f"**📊 今日实时数据**\n👤 独立用户 (UV)：**{uv}**\n🃏 翻牌总次数：**{flips}**"},
                {"tag": "hr"},
                {"tag": "markdown", "content": f"**❓ 最新用户提问 (去重)**\n{q_display or '暂无提问'}"},
                {"tag": "note", "content": {"tag": "plain_text", "content": "数据由 GitHub Actions 自动推送"}}
            ]}
        }
    }
    requests.post(FEISHU_WEBHOOK, json=card)

if __name__ == "__main__":
    try:
        uv, flips, qs = get_stats()
        push_feishu(uv, flips, qs)
        print("✅ 飞书推送成功")
    except Exception as e:
        print(f"❌ 运行出错: {e}")
