import os
import requests
from datetime import datetime, timezone, timedelta
from supabase import create_client, Client

# --- 1. 配置 ---
SUPABASE_URL = "https://ybragvmvirddqfotqxig.supabase.co"
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/db9c21f0-9453-410d-ae0e-c9116a8dc612"
BEIJING_TZ = timezone(timedelta(hours=8))

def get_stats():
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    # 1. 核心：直接调用数据库内部函数，拿到和你 SQL 后台一模一样的数字
    print("--- 正在通过 RPC 调用获取聚合结果 ---")
    rpc_res = supabase.rpc("fetch_accurate_stats").execute()
    data = rpc_res.data[0] if rpc_res.data else {"today_flips": 0, "today_uv": 0}
    
    uv = data.get("today_uv", 0)
    flips = data.get("today_flips", 0)

    # 2. 获取最新提问 (带去重)
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
            
    return uv, flips, qs

def push_to_feishu(uv, flips, qs):
    now_str = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M")
    
    # 使用纯文本，彻底解决 parse error 问题
    content = (
        f"🔮 **Zen Tarot 运营简报**\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📅 统计日期：{datetime.now(BEIJING_TZ).strftime('%Y-%m-%d')}\n"
        f"👤 独立用户 (UV)：**{uv}**\n"
        f"🃏 占卜总次数：**{flips}**\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"❓ **最新提问：**\n" + "\n".join(qs) + "\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⏰ 更新时间：{now_str}"
    )

    payload = {"msg_type": "text", "content": {"text": content}}
    r = requests.post(FEISHU_WEBHOOK, json=payload, timeout=10)
    print(f"飞书返回: {r.text}")

if __name__ == "__main__":
    try:
        u, f, q = get_stats()
        push_to_feishu(u, f, q)
    except Exception as e:
        print(f"❌ 运行报错: {e}")
