import os
import requests
from datetime import datetime, timezone, timedelta
from supabase import create_client, Client

# --- 配置 ---
SUPABASE_URL = "https://ybragvmvirddqfotqxig.supabase.co"
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/db9c21f0-9453-410d-ae0e-c9116a8dc612"
BEIJING_TZ = timezone(timedelta(hours=8))

def get_accurate_data():
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    # 1. 严格锁定北京时间今日 0 点对应的 UTC 时间
    now_bj = datetime.now(BEIJING_TZ)
    today_0am_bj = now_bj.replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = today_0am_bj.astimezone(timezone.utc).isoformat()
    
    print(f"--- 统计开始时间 (UTC): {start_utc} ---")

    # 2. 物理拉取今日所有 ID (防止数据库 Count 逻辑漂移)
    # 我们只拉取 anonymous_id，分批次拉取
    all_ids = []
    offset = 0
    while True:
        # 使用 order("id") 确保分页绝对稳定，不重不漏
        res = supabase.table("tarot_history")\
            .select("anonymous_id")\
            .gte("created_at", start_utc)\
            .order("id")\
            .range(offset, offset + 999).execute()
        
        batch = res.data or []
        all_ids.extend([row['anonymous_id'] for row in batch])
        if len(batch) < 1000:
            break
        offset += 1000
    
    total_flips = len(all_ids)
    uv = len(set(all_ids))

    # 3. 抓取最新的 30 条问题
    q_res = supabase.table("tarot_history")\
        .select("question, created_at")\
        .not_.is_("question", "null")\
        .order("created_at", desc=True)\
        .limit(60).execute() # 多取一点用来去重
    
    seen_qs = set()
    final_qs = []
    for row in (q_res.data or []):
        q = (row['question'] or "").strip()
        if len(q) > 2 and q not in seen_qs:
            seen_qs.add(q)
            # 转换时间格式
            utc_time = datetime.fromisoformat(row['created_at'].replace('Z', '+00:00'))
            bj_time = utc_time.astimezone(BEIJING_TZ).strftime("%H:%M")
            final_qs.append(f"· [{bj_time}] {q}")
        if len(final_qs) >= 30: break
            
    return uv, total_flips, final_qs

def push_to_feishu(uv, flips, qs):
    now_str = datetime.now(BEIJING_TZ).strftime("%H:%M")
    
    # 构建飞书消息
    message = (
        f"🔮 **Zen Tarot 半小时简报**\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📅 统计日期：{datetime.now(BEIJING_TZ).strftime('%Y-%m-%d')}\n"
        f"👤 今日独立用户 (UV)：**{uv}**\n"
        f"🃏 今日占卜总次数：**{flips}**\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"❓ **最新 30 个问题：**\n" + "\n".join(qs) + "\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⏰ 更新时间：{now_str} (每30分钟自动抓取)"
    )

    payload = {"msg_type": "text", "content": {"text": message}}
    requests.post(FEISHU_WEBHOOK, json=payload, timeout=15)

if __name__ == "__main__":
    try:
        u, f, q = get_accurate_data()
        push_to_feishu(u, f, q)
        print(f"✅ 执行成功: UV={u}, Flips={f}")
    except Exception as e:
        print(f"❌ 运行失败: {e}")
