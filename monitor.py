import os
import requests
from datetime import datetime, timezone, timedelta
from supabase import create_client, Client

# --- 配置 ---
SUPABASE_URL = "https://ybragvmvirddqfotqxig.supabase.co"
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/db9c21f0-9453-410d-ae0e-c9116a8dc612"
BEIJING_TZ = timezone(timedelta(hours=8))

def get_stats():
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    print("--- 正在通过 RPC 获取最终准确数据 ---")
    # 调用新函数名：get_daily_stats_final
    rpc_res = supabase.rpc("get_daily_stats_final").execute()
    stats = rpc_res.data[0] if rpc_res.data else {"t_flips": 0, "t_uv": 0}
    
    flips = stats.get("t_flips", 0)
    uv = stats.get("t_uv", 0)

    # 获取最新 5 条提问，做极简处理
    q_res = supabase.table("tarot_history")\
        .select("question")\
        .not_.is_("question", "null")\
        .order("created_at", desc=True)\
        .limit(30).execute()
    
    seen, qs = set(), []
    for row in (q_res.data or []):
        q = (row['question'] or "").strip().replace("\n", " ")
        if len(q) > 2 and q not in seen:
            seen.add(q)
            qs.append(f"· {q}")
        if len(qs) >= 5: break
            
    return uv, flips, qs

def push_feishu(uv, flips, qs):
    now_str = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M")
    
    # 构建纯文本消息，绕过复杂的卡片解析器
    # 使用 Markdown 格式在飞书机器人中依然有良好的视觉效果
    content = f"🔮 **Zen Tarot 运营简报**\n" \
              f"---------------------------\n" \
              f"📅 统计日期：{datetime.now(BEIJING_TZ).strftime('%Y-%m-%d')}\n" \
              f"👤 独立用户 (UV)：**{uv}**\n" \
              f"🃏 占卜总次数：**{flips}**\n" \
              f"---------------------------\n" \
              f"❓ **最新提问：**\n" + "\n".join(qs) + \
              f"\n\n⏰ 更新时间：{now_str}"

    payload = {
        "msg_type": "text", # 这一行是关键，改用纯文本模式
        "content": {
            "text": content
        }
    }
    
    r = requests.post(FEISHU_WEBHOOK, json=payload, timeout=10)
    print(f"飞书返回结果: {r.text}")

if __name__ == "__main__":
    try:
        u, f, q = get_stats()
        push_feishu(u, f, q)
    except Exception as e:
        print(f"❌ 运行报错: {e}")
