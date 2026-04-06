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
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    # 调用你刚才在 Supabase 里创建成功的函数
    print("--- 正在调用 RPC 获取聚合数据 ---")
    rpc_res = supabase.rpc("get_daily_stats").execute()
    stats = rpc_res.data[0] if rpc_res.data else {"t_flips": 0, "t_uv": 0}
    
    flips = stats.get("t_flips", 0)
    uv = stats.get("t_uv", 0)
    print(f"聚合结果: UV={uv}, 次数={flips}")

    # 获取最新 5 条提问 (极简展示，防止卡片过长)
    q_res = supabase.table("tarot_history")\
        .select("question, created_at")\
        .not_.is_("question", "null")\
        .order("created_at", desc=True)\
        .limit(50).execute()
    
    seen, qs = set(), []
    for row in (q_res.data or []):
        q = (row['question'] or "").strip().replace('"', "'")
        if len(q) > 2 and q not in seen:
            seen.add(q)
            utc_dt = datetime.fromisoformat(row['created_at'].replace('Z', '+00:00'))
            bj_time = utc_dt.astimezone(BEIJING_TZ).strftime("%H:%M")
            qs.append(f"• [{bj_time}] {q}")
        if len(qs) >= 5: break # 只拿5条，最稳妥
            
    return uv, flips, qs

def push_feishu(uv, flips, qs):
    now_str = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M")
    q_text = "\n".join(qs) if qs else "今日暂无有效提问"

    # --- ！！！修正后的扁平化结构 ！！！ ---
    payload = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": "🔮 Zen Tarot 运营看板"},
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
                    "content": {"tag": "plain_text", "content": f"更新于 {now_str}"}
                }
            ]
        }
    }
    
    # 强制直接传字典对象，不要手动 dumps
    r = requests.post(FEISHU_WEBHOOK, json=payload, timeout=10)
    print(f"飞书返回结果: {r.text}")

if __name__ == "__main__":
    try:
        u, f, q = get_stats()
        push_feishu(u, f, q)
    except Exception as e:
        print(f"❌ 运行报错: {e}")
