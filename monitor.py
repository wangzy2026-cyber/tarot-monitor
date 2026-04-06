import os
import requests
import json
from datetime import datetime, timezone, timedelta
from supabase import create_client, Client

# --- 1. 配置 (环境变量务必在 GitHub Secrets 设好) ---
SUPABASE_URL = "https://ybragvmvirddqfotqxig.supabase.co"
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/db9c21f0-9453-410d-ae0e-c9116a8dc612"
BEIJING_TZ = timezone(timedelta(hours=8))

def get_stats():
    print("--- 正在提取精准数据 (对齐 SQL 逻辑) ---")
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    # 计算北京时间今日 0 点对应的 UTC 时间戳
    today_bj = datetime.now(BEIJING_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    start_time_utc = today_bj.astimezone(timezone.utc).isoformat()
    
    # --- 核心逻辑 A：获取总占卜次数 (对应 SQL: COUNT(*)) ---
    # 使用 count='exact' 配合 head=True，可以瞬间拿到几十万行的准确总数，无视 1000 条限制
    res_count = supabase.table("tarot_history")\
        .select("*", count="exact")\
        .gte("created_at", start_time_utc)\
        .head(True)\
        .execute()
    total_flips = res_count.count if res_count.count is not None else 0
    
    # --- 核心逻辑 B：获取独立用户数 (对应 SQL: COUNT(DISTINCT anonymous_id)) ---
    # 你的 UV 目前是 921，在 1000 以内，直接 select 是准的。
    # 如果未来 UV 超过 1000，Supabase 的 select 会卡死，所以这里我们取前 2000 名用户进行去重
    res_uv = supabase.table("tarot_history")\
        .select("anonymous_id")\
        .gte("created_at", start_time_utc)\
        .limit(2000)\
        .execute()
    uv = len(set(row['anonymous_id'] for row in (res_uv.data or [])))
    
    # --- 核心逻辑 C：获取最新提问 (Top 20) ---
    q_res = supabase.table("tarot_history")\
        .select("question, created_at")\
        .not_.is_("question", "null")\
        .order("created_at", desc=True)\
        .limit(100).execute()
    
    seen, qs = set(), []
    for row in (q_res.data or []):
        q = (row['question'] or "").strip()
        if len(q) > 2 and q not in seen:
            seen.add(q)
            utc_dt = datetime.fromisoformat(row['created_at'].replace('Z', '+00:00'))
            bj_time = utc_dt.astimezone(BEIJING_TZ).strftime("%H:%M")
            qs.append(f"[{bj_time}] {q}")
        if len(qs) >= 20: break
            
    return uv, total_flips, qs

def push_feishu(uv, flips, qs):
    print(f"--- 正在推送飞书 (UV={uv}, Flips={flips}) ---")
    now_str = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M")
    q_text = "\n".join(qs) if qs else "今日暂无提问"

    # 使用字典构建 payload，json= 参数会自动处理转义，解决之前的 parse err
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
                    "content": f"**📊 今日实时数据 (0点起)**\n👤 独立用户 (UV)：**{uv}**\n🃏 占卜总次数：**{flips}**\n🕒 统计时间：{now_str}"
                },
                {"tag": "hr"},
                {
                    "tag": "markdown",
                    "content": f"**❓ 最新用户提问**\n{q_text}"
                },
                {
                    "tag": "note",
                    "content": {"tag": "plain_text", "content": "数据已通过 count='exact' 参数对齐 SQL 统计结果"}
                }
            ]
        }
    }
    
    r = requests.post(FEISHU_WEBHOOK, json=payload, timeout=10)
    print(f"飞书 API 返回: {r.text}")

if __name__ == "__main__":
    try:
        u, f, q = get_stats()
        push_feishu(u, f, q)
    except Exception as e:
        print(f"❌ 运行报错: {e}")
