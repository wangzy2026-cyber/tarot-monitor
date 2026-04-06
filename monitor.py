import os
import requests
from datetime import datetime, timezone, timedelta
from supabase import create_client, Client

# --- 1. 基础配置 ---
SUPABASE_URL = "https://ybragvmvirddqfotqxig.supabase.co"
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/db9c21f0-9453-410d-ae0e-c9116a8dc612"
BEIJING_TZ = timezone(timedelta(hours=8))

def get_final_data():
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    # --- 逻辑 A: 获取 14141 和 982 那组数据 ---
    # 模拟 SQL: WHERE DATE(created_at) = CURRENT_DATE
    # 我们取北京时间今天 0 点对应的 UTC 时间戳
    today_bj = datetime.now(BEIJING_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = today_bj.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    
    # 查总次数 (Exact Count)
    res_count = supabase.table("tarot_history").select("id", count="exact").gte("created_at", start_utc).limit(1).execute()
    total_flips = res_count.count
    
    # 查独立用户 (UV) - 循环抓取直到抓完所有 ID
    all_users = set()
    offset = 0
    while True:
        r = supabase.table("tarot_history").select("anonymous_id").gte("created_at", start_utc).range(offset, offset + 999).execute()
        if not r.data: break
        all_users.update([row['anonymous_id'] for row in r.data])
        if len(r.data) < 1000: break
        offset += 1000
    uv = len(all_users)

    # --- 逻辑 B: 获取最新提问列表 (严格对齐你截图里的 SQL) ---
    # 排除 null, 长度 > 2, 倒序
    q_res = supabase.table("tarot_history")\
        .select("question")\
        .not_.is_("question", "null")\
        .order("created_at", desc=True)\
        .limit(100).execute()
    
    seen_qs = set()
    final_qs = []
    for row in (q_res.data or []):
        q = (row['question'] or "").strip()
        if len(q) > 2 and q not in seen_qs:
            seen_qs.add(q)
            final_qs.append(f"· {q}")
        if len(final_qs) >= 10: break # 取前10条最稳
            
    return uv, total_flips, final_qs

def push_to_feishu(uv, flips, qs):
    # 既然卡片老是报错，我们就用飞书最原始、最不可能报错的 text 格式
    # 这也是为了确保你“能收到”
    time_str = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M")
    
    message_text = (
        f"🔮 **Zen Tarot 运营简报**\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📅 统计日期：{datetime.now(BEIJING_TZ).strftime('%Y-%m-%d')}\n"
        f"👤 独立用户 (UV)：**{uv}**\n"
        f"🃏 占卜总次数：**{flips}**\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"❓ **最新提问：**\n" + "\n".join(qs) + "\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⏰ 更新时间：{time_str}"
    )

    payload = {
        "msg_type": "text",
        "content": {
            "text": message_text
        }
    }
    
    r = requests.post(FEISHU_WEBHOOK, json=payload, timeout=10)
    print(f"飞书返回结果: {r.text}")

if __name__ == "__main__":
    try:
        u, f, q = get_final_data()
        push_to_feishu(u, f, q)
        print(f"✅ 成功! 抓取到 UV={u}, Flips={f}")
    except Exception as e:
        print(f"❌ 还是崩了: {e}")
