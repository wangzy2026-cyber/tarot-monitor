import os
import requests
from datetime import datetime, timezone, timedelta
from supabase import create_client, Client

# --- 配置 ---
SUPABASE_URL = "https://ybragvmvirddqfotqxig.supabase.co"
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/db9c21f0-9453-410d-ae0e-c9116a8dc612"
BEIJING_TZ = timezone(timedelta(hours=8))

def get_stats_force():
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    # 锁定北京时间 2026-04-06 的 UTC 范围
    # 4/6 00:00 BJ = 4/5 16:00 UTC
    # 4/6 23:59 BJ = 4/6 15:59 UTC
    start_utc = "2026-04-05T16:00:00.000Z"
    end_utc = "2026-04-06T15:59:59.999Z"
    
    print(f"--- 物理扫表开始: {start_utc} 至 {end_utc} ---")

    all_raw_data = []
    offset = 0
    
    # 物理扫表：一页一页拉，直到拉完 1.4 万条
    while True:
        res = supabase.table("tarot_history") \
            .select("anonymous_id") \
            .gte("created_at", start_utc) \
            .lte("created_at", end_utc) \
            .range(offset, offset + 999) \
            .execute()
        
        batch = res.data or []
        if not batch:
            break
        all_raw_data.extend(batch)
        print(f"已拉取 {len(all_raw_data)} 条...")
        if len(batch) < 1000:
            break
        offset += 1000

    # 在内存里物理点数
    total_flips = len(all_raw_data)
    uv = len(set(item['anonymous_id'] for item in all_raw_data))
    
    print(f"物理点数完成: UV={uv}, Flips={total_flips}")

    # 获取最新 5 条提问
    q_res = supabase.table("tarot_history")\
        .select("question")\
        .not_.is_("question", "null")\
        .order("created_at", desc=True)\
        .limit(30).execute()
    
    seen, qs = set(), []
    for row in (q_res.data or []):
        q = (row['question'] or "").strip()
        if len(q) > 2 and q not in seen:
            seen.add(q)
            qs.append(f"· {q}")
        if len(qs) >= 5: break
            
    return uv, total_flips, qs

def push_to_feishu(uv, flips, qs):
    time_str = datetime.now(BEIJING_TZ).strftime("%H:%M")
    message = (
        f"🔮 **Zen Tarot 运营简报**\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📅 统计日期：2026-04-06\n"
        f"👤 独立用户 (UV)：**{uv}**\n"
        f"🃏 占卜总次数：**{flips}**\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"❓ **最新提问：**\n" + "\n".join(qs) + "\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⏰ 更新时间：{time_str}"
    )
    requests.post(FEISHU_WEBHOOK, json={"msg_type": "text", "content": {"text": message}})

if __name__ == "__main__":
    try:
        u, f, q = get_stats_force()
        push_to_feishu(u, f, q)
    except Exception as e:
        print(f"❌ 运行报错: {e}")
