import os
import requests
from datetime import datetime, timezone, timedelta
from supabase import create_client, Client

# --- 1. 配置 ---
SUPABASE_URL = "https://ybragvmvirddqfotqxig.supabase.co"
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/db9c21f0-9453-410d-ae0e-c9116a8dc612"
BEIJING_TZ = timezone(timedelta(hours=8))

def get_interval_only():
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    # 获取当前北京时间及 30 分钟前
    now_bj = datetime.now(BEIJING_TZ)
    half_hour_ago_bj = now_bj - timedelta(minutes=30)
    
    # 转换成 UTC 给 Supabase 过滤
    start_utc = half_hour_ago_bj.astimezone(timezone.utc).isoformat()
    
    print(f"--- 正在提取增量数据: {half_hour_ago_bj.strftime('%H:%M')} 至今 ---")

    # 1. 直接拉取最近 30 分钟的所有数据 (不分页，一次性拉取 2000 条上限，绝对够用)
    res = supabase.table("tarot_history")\
        .select("anonymous_id, question, created_at")\
        .gte("created_at", start_utc)\
        .order("created_at", desc=True)\
        .limit(2000).execute()
    
    rows = res.data or []
    
    # 2. 统计这半小时的数据
    interval_flips = len(rows)
    interval_uv = len(set(r['anonymous_id'] for r in rows))

    # 3. 提取这半小时内最新的 30 个问题 (去重)
    seen_qs = set()
    qs_list = []
    for r in rows:
        q = (r['question'] or "").strip()
        if len(q) > 2 and q not in seen_qs:
            seen_qs.add(q)
            # 解析时间（兼容带时区的格式）
            clean_ts = r['created_at'].split('+')[0].split('.')[0].replace('Z','')
            dt_bj = datetime.strptime(clean_ts, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).astimezone(BEIJING_TZ)
            qs_list.append(f"· [{dt_bj.strftime('%H:%M')}] {q}")
        if len(qs_list) >= 30: break
            
    return interval_uv, interval_flips, qs_list

def push_to_feishu(uv, flips, qs):
    now_str = datetime.now(BEIJING_TZ).strftime("%H:%M")
    
    # 极简增量模板
    message = (
        f"⚡ **Zen Tarot 30min 实时快报**\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⏱️ 统计区间：过去 30 分钟\n"
        f"📈 新增占卜：**+{flips}** 次\n"
        f"👤 活跃用户：**{uv}** 人\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"❓ **最新 30 条提问：**\n" + ("\n".join(qs) if qs else "此时间段内暂无提问") + "\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⏰ 更新时间：{now_str}"
    )

    payload = {"msg_type": "text", "content": {"text": message}}
    requests.post(FEISHU_WEBHOOK, json=payload, timeout=10)

if __name__ == "__main__":
    try:
        u, f, q = get_interval_only()
        push_to_feishu(u, f, q)
    except Exception as e:
        print(f"❌ 运行报错: {e}")
