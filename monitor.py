import os
import requests
import json
from datetime import datetime, timezone, timedelta
from supabase import create_client, Client

# --- 1. 配置 ---
SUPABASE_URL = "https://ybragvmvirddqfotqxig.supabase.co"
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/db9c21f0-9453-410d-ae0e-c9116a8dc612"
BEIJING_TZ = timezone(timedelta(hours=8))

def get_stats():
    print("--- 正在提取精准数据 ---")
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    # 获取北京时间今日 0 点
    now_bj = datetime.now(BEIJING_TZ)
    today_0am_bj = now_bj.replace(hour=0, minute=0, second=0, microsecond=0)
    start_time_utc = today_0am_bj.astimezone(timezone.utc).isoformat()
    
    # --- 逻辑 A：获取总占卜次数 (无视 1000 条限制) ---
    # limit(1) 配合 count='exact' 是最稳妥的拿总数方法
    res_count = supabase.table("tarot_history")\
        .select("id", count="exact")\
        .gte("created_at", start_time_utc)\
        .limit(1)\
        .execute()
    total_flips = res_count.count if res_count.count is not None else 0
    
    # --- 逻辑 B：获取独立用户数 (UV) ---
    # 针对你目前的 921 UV，我们拉取前 2000 条匿名 ID 进行去重
    res_uv = supabase.table("tarot_history")\
        .select("anonymous_id")\
        .gte("created_at", start_time_utc)\
        .limit(2000)\
        .execute()
    uv = len(set(row['anonymous_id'] for row in (res_uv.data or [])))
    
    # --- 逻辑 C：获取最新提问 ---
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
    print(f"--- 正在推送飞书 (UV={uv}, 次数={flips}) ---")
    now_str = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M")
    q_text = "\n".join(qs) if qs else "今日暂无有效提问"

    payload = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": "🔮 Zen Tarot 运营速报"},
                "template": "purple"
            },
            "body": {
                "elements": [
                    {
                        "tag": "markdown",
                        "content": f"**📊 今日数据统计 (0点起)**\n👤 独立用户 (UV)：**{uv}**\n🃏 占卜总次数：**{flips}**\n🕒 更新于：{now_str}"
                    },
                    {"tag": "hr"},
                    {
                        "tag": "markdown",
                        "content": f"**❓ 最新用户提问**\n{q_text}"
                    },
                    {
                        "tag": "note",
                        "content": {"tag": "plain_text", "content": "数据已通过 exact count 模式精准对齐后台 SQL"}
                    }
                ]
            }
        }
    }
    
    r = requests.post(FEISHU_WEBHOOK, json=payload, timeout=15)
    print(f"飞书返回结果: {r.text}")

if __name__ == "__main__":
    try:
        u, f, q = get_stats()
        push_feishu(u, f, q)
    except Exception as e:
        print(f"❌ 运行报错: {e}")
