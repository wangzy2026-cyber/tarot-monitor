import os
import requests
from datetime import datetime, timezone, timedelta
from supabase import create_client, Client

# --- 1. 配置 ---
SUPABASE_URL = "https://ybragvmvirddqfotqxig.supabase.co"
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/db9c21f0-9453-410d-ae0e-c9116a8dc612"
BEIJING_TZ = timezone(timedelta(hours=8))

def get_data():
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    # 设定北京时间今日日期字符串 (例如 '2026-04-06')
    today_str = datetime.now(BEIJING_TZ).strftime('%Y-%m-%d')
    
    print(f"--- 正在提取 {today_str} 的精准数据 ---")

    # --- 核心逻辑 A: 获取总次数 ---
    # 利用 Supabase 的文本搜索或过滤器，模拟 DATE(created_at)
    # 我们直接用最原始的 gte 和 lt 锁定北京时间的这 24 小时
    start_utc = (datetime.now(BEIJING_TZ).replace(hour=0,minute=0,second=0,microsecond=0)).astimezone(timezone.utc).isoformat()
    end_utc = (datetime.now(BEIJING_TZ).replace(hour=23,minute=59,second=59,microsecond=0)).astimezone(timezone.utc).isoformat()

    # 直接拿 Exact Count，不拉取数据体，彻底解决翻倍问题
    res_count = supabase.table("tarot_history")\
        .select("id", count="exact")\
        .gte("created_at", start_utc)\
        .lte("created_at", end_utc)\
        .limit(1).execute()
    
    total_flips = res_count.count if res_count.count else 0

    # --- 核心逻辑 B: 获取独立用户 (UV) ---
    # 为了绝对准确，我们只拉取 anonymous_id，并强制按 id 排序分页，防止重复抓取
    all_users = set()
    last_id = "00000000-0000-0000-0000-000000000000" # UUID 初始值
    
    while True:
        r = supabase.table("tarot_history")\
            .select("id, anonymous_id")\
            .gte("created_at", start_utc)\
            .lte("created_at", end_utc)\
            .gt("id", last_id)\
            .order("id")\
            .limit(1000).execute()
        
        batch = r.data or []
        if not batch: break
        
        for row in batch:
            all_users.add(row['anonymous_id'])
            last_id = row['id'] # 记录最后一条 UUID 游标
            
        if len(batch) < 1000: break
    
    uv = len(all_users)

    # --- 核心逻辑 C: 最新提问 ---
    q_res = supabase.table("tarot_history")\
        .select("question")\
        .not_.is_("question", "null")\
        .order("created_at", desc=True)\
        .limit(50).execute()
    
    qs = []
    seen = set()
    for row in (q_res.data or []):
        q = (row['question'] or "").strip()
        if len(q) > 2 and q not in seen:
            seen.add(q)
            qs.append(f"· {q}")
        if len(qs) >= 10: break
            
    return uv, total_flips, qs

def push_to_feishu(uv, flips, qs):
    time_str = datetime.now(BEIJING_TZ).strftime("%H:%M")
    
    # 纯文本格式是目前最稳的，绝对不会因为 JSON 嵌套报错
    message = (
        f"🔮 **Zen Tarot 运营简报**\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📅 统计日期：{datetime.now(BEIJING_TZ).strftime('%Y-%m-%d')}\n"
        f"👤 独立用户 (UV)：**{uv}**\n"
        f"🃏 占卜总次数：**{flips}**\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"❓ **最新提问：**\n" + "\n".join(qs) + "\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⏰ 更新时间：{datetime.now(BEIJING_TZ).strftime('%Y-%m-%d')} {time_str}"
    )

    payload = {"msg_type": "text", "content": {"text": message}}
    requests.post(FEISHU_WEBHOOK, json=payload, timeout=10)

if __name__ == "__main__":
    u, f, q = get_data()
    push_to_feishu(u, f, q)
