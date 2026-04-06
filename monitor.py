import os
import requests
from datetime import datetime, timezone, timedelta
from supabase import create_client, Client

# --- 1. 配置 ---
SUPABASE_URL = "https://ybragvmvirddqfotqxig.supabase.co"
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/db9c21f0-9453-410d-ae0e-c9116a8dc612"
BEIJING_TZ = timezone(timedelta(hours=8))

def get_data_no_bullshit():
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    # 这一步是核心：我们不再自己算 UTC，我们问数据库现在是北京时间几号
    db_now = supabase.rpc("get_bj_date").execute()
    # 如果 rpc 没建，我们手动定死：
    target_date = datetime.now(BEIJING_TZ).strftime('%Y-%m-%d')
    
    print(f"--- 目标日期: {target_date} ---")

    # --- 彻底放弃 range 和 gte，改用 filter 匹配日期字符串 ---
    # 这种写法在 Supabase 里最稳，直接匹配数据库转换后的日期字符串
    res = supabase.table("tarot_history")\
        .select("anonymous_id")\
        .filter("created_at", "gte", f"{target_date} 00:00:00+08")\
        .filter("created_at", "lte", f"{target_date} 23:59:59+08")\
        .execute()
    
    raw_data = res.data or []
    total_flips = len(raw_data)
    uv = len(set(item['anonymous_id'] for item in raw_data))

    # 如果上面那个数据还是大的离谱，说明 gte 还是失效了
    # 我们用最后一招：拉取最近 20000 条，在 Python 里根据字符串强行过滤
    if total_flips > 20000:
        print("检测到数据异常，启动强力物理过滤...")
        res_brute = supabase.table("tarot_history")\
            .select("anonymous_id, created_at")\
            .order("created_at", desc=True)\
            .limit(20000).execute()
            
        filtered = [
            row for row in (res_brute.data or [])
            if (datetime.fromisoformat(row['created_at'].replace('Z', '+00:00')) + timedelta(hours=8)).strftime('%Y-%m-%d') == target_date
        ]
        total_flips = len(filtered)
        uv = len(set(row['anonymous_id'] for row in filtered))

    # 获取提问列表 (去重)
    q_res = supabase.table("tarot_history")\
        .select("question")\
        .not_.is_("question", "null")\
        .order("created_at", desc=True)\
        .limit(50).execute()
    
    seen, qs = set(), []
    for row in (q_res.data or []):
        q = (row['question'] or "").strip()
        if len(q) > 2 and q not in seen:
            seen.add(q)
            qs.append(f"· {q}")
        if len(qs) >= 10: break
            
    return uv, total_flips, qs

def push_to_feishu(uv, flips, qs):
    time_str = datetime.now(BEIJING_TZ).strftime("%H:%M")
    message = (
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
    requests.post(FEISHU_WEBHOOK, json={"msg_type": "text", "content": {"text": message}})

if __name__ == "__main__":
    u, f, q = get_data_no_bullshit()
    push_to_feishu(u, f, q)
