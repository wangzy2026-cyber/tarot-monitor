import os
import requests
from datetime import datetime, timezone, timedelta
from supabase import create_client, Client

# --- 配置 ---
SUPABASE_URL = "https://ybragvmvirddqfotqxig.supabase.co"
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/db9c21f0-9453-410d-ae0e-c9116a8dc612"
BEIJING_TZ = timezone(timedelta(hours=8))

def get_interval_data():
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    # 1. 设定时间范围：过去 30 分钟
    now_bj = datetime.now(BEIJING_TZ)
    half_hour_ago_bj = now_bj - timedelta(minutes=30)
    
    start_utc = half_hour_ago_bj.astimezone(timezone.utc).isoformat()
    print(f"--- 抓取增量区间: {half_hour_ago_bj.strftime('%H:%M')} 至 {now_bj.strftime('%H:%M')} ---")

    # 2. 抓取这 30 分钟内的所有数据 (量小，绝对不会翻倍)
    res = supabase.table("tarot_history")\
        .select("anonymous_id, question, created_at")\
        .gte("created_at", start_utc)\
        .order("created_at", desc=True)\
        .execute()
    
    data = res.data or []
    interval_flips = len(data)
    interval_uv = len(set(item['anonymous_id'] for item in data))

    # 3. 提取这半小时内最新的 30 个问题 (去重)
    seen_qs = set()
    final_qs = []
    for row in data:
        q = (row['question'] or "").strip()
        if len(q) > 2 and q not in seen_qs:
            seen_qs.add(q)
            # 格式化时间
            utc_time = datetime.fromisoformat(row['created_at'].replace('Z', '+00:00'))
            bj_time = utc_time.astimezone(BEIJING_TZ).strftime("%H:%M")
            final_qs.append(f"· [{bj_time}] {q}")
        if len(final_qs) >= 30: break
            
    return interval_uv, interval_flips, final_qs

def push_to_feishu(uv, flips, qs):
    now_str = datetime.now(BEIJING_TZ).strftime("%H:%M")
    
    # 重新设计的简报模板
    message = (
        f"⚡ **Zen Tarot 实时增量速报**\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⏱️ 统计区间：过去 30 分钟\n"
        f"📈 新增占卜：**{flips}** 次\n"
        f"👥 活跃用户：**{uv}** 人\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"❓ **最近 30 条真实提问：**\n" + ("\n".join(qs) if qs else "期间暂无提问") + "\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⏰ 推送时间：{now_str} (自动循环)"
    )

    payload = {"msg_type": "text", "content": {"text": message}}
    r = requests.post(FEISHU_WEBHOOK, json=payload, timeout=15)
    print(f"飞书返回: {r.text}")

if __name__ == "__main__":
    try:
        u, f, q = get_interval_data()
        push_to_feishu(u, f, q)
    except Exception as e:
        print(f"❌ 运行报错: {e}")
