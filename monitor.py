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
    
    print("--- 正在调用 RPC 获取聚合数据 ---")
    rpc_res = supabase.rpc("get_daily_stats").execute()
    stats = rpc_res.data[0] if rpc_res.data else {"t_flips": 0, "t_uv": 0}
    
    flips = stats.get("t_flips", 0)
    uv = stats.get("t_uv", 0)
    print(f"聚合结果: UV={uv}, 次数={flips}")

    # 获取最新 5 条提问
    q_res = supabase.table("tarot_history")\
        .select("question, created_at")\
        .not_.is_("question", "null")\
        .order("created_at", desc=True)\
        .limit(30).execute()
    
    seen, qs = set(), []
    for row in (q_res.data or []):
        q = (row['question'] or "").strip().replace('"', "'")
        if len(q) > 2 and q not in seen:
            seen.add(q)
            utc_dt = datetime.fromisoformat(row['created_at'].replace('Z', '+00:00'))
            bj_time = utc_dt.astimezone(BEIJING_TZ).strftime("%H:%M")
            qs.append(f"• [{bj_time}] {q}")
        if len(qs) >= 5: break
            
    return uv, flips, qs

def push_feishu(uv, flips, qs):
    now_str = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M")
    q_text = "\n".join(qs) if qs else "今日暂无有效提问"

    # --- 这里是物理意义上的最简结构，绝不嵌套 ---
    payload = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": "🔮 Zen Tarot 运营速报"},
                "template": "purple"
            },
            "elements": [
                {
                    "tag": "markdown",
                    "content": f"**📊 今日实时数据 (SQL聚合)**\n👤 独立用户 (UV)：**{uv}**\n🃏 占卜总次数：**{flips:,}**"
                },
                {"tag": "hr"},
                {
                    "tag": "markdown",
                    "content": f"**❓ 最新提问**\n{q_text}"
                },
                {
                    "tag": "note",
                    "content": {"tag": "plain_text", "content": f"最后更新：{now_str}"}
                }
            ]
        }
    }
    
    # 强制不使用任何 json.dumps，由 requests 库处理
    r = requests.post(FEISHU_WEBHOOK, json=payload, timeout=10)
    print(f"飞书返回结果: {r.text}")

if __name__ == "__main__":
    try:
        u, f, q = get_stats()
        push_feishu(u, f, q)
    except Exception as e:
        print(f"❌ 运行报错: {e}")
