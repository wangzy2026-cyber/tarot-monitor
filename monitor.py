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

def get_stats_perfectly():
    print("--- 正在执行绝对精准统计 ---")
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    # 严格计算北京时间今日 0 点起始点
    today_bj_0am = datetime.now(BEIJING_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    start_time_utc = today_bj_0am.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    
    print(f"统计起始点 (UTC): {start_time_utc}")

    # --- 逻辑 A: 占卜总次数 (准确对齐 SQL COUNT(*)) ---
    # 使用 exact count + limit(0) 不取任何数据，只取总数，无视 1000 条限制
    res_total = supabase.table("tarot_history")\
        .select("id", count="exact")\
        .gte("created_at", start_time_utc)\
        .limit(1).execute()
    total_flips = res_total.count if res_total.count is not None else 0

    # --- 逻辑 B: 独立用户数 (准确对齐 SQL COUNT(DISTINCT anonymous_id)) ---
    # 这里我们不再通过 Python 分页，因为分页容易导致重叠或遗漏
    # 既然你之前的 SQL 能跑出 956，说明数据在数据库里是清晰的
    # 我们拉取今日所有 anonymous_id，一次性处理（针对 1.3w 数据量没问题）
    all_ids = []
    offset = 0
    while True:
        r = supabase.table("tarot_history")\
            .select("anonymous_id")\
            .gte("created_at", start_time_utc)\
            .order("created_at")\
            .range(offset, offset + 999)\
            .execute()
        
        batch = r.data or []
        all_ids.extend([row['anonymous_id'] for row in batch])
        if len(batch) < 1000:
            break
        offset += 1000
    
    uv = len(set(all_ids))
    print(f"最终校验: UV={uv}, Flips={total_flips}")

    # --- 逻辑 C: 最新提问 (Top 15) ---
    q_res = supabase.table("tarot_history")\
        .select("question, created_at")\
        .not_.is_("question", "null")\
        .order("created_at", desc=True)\
        .limit(100).execute()
    
    seen, qs = set(), []
    for row in (q_res.data or []):
        q = (row['question'] or "").strip().replace('"', "'")
        if len(q) > 2 and q not in seen:
            seen.add(q)
            utc_dt = datetime.fromisoformat(row['created_at'].replace('Z', '+00:00'))
            bj_time = utc_dt.astimezone(BEIJING_TZ).strftime("%H:%M")
            qs.append(f"• [{bj_time}] {q}")
        if len(qs) >= 15: break
            
    return uv, total_flips, qs

def push_feishu(uv, flips, qs):
    print("--- 正在推送飞书 ---")
    now_str = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M")
    q_text = "\n".join(qs) if qs else "今日暂无提问数据"

    # 彻底简化 JSON 结构，修复 parse json err
    card_payload = {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": "🔮 Zen Tarot 运营速报"},
                "template": "purple"
            },
            "elements": [
                {
                    "tag": "markdown",
                    "content": f"**📊 今日实时数据 (0点起)**\n👤 独立用户 (UV)：**{uv}**\n🃏 占卜总次数：**{flips:,}**\n🕒 统计时间：{now_str}"
                },
                {"tag": "hr"},
                {
                    "tag": "markdown",
                    "content": f"**❓ 最新用户提问**\n{q_text}"
                }
            ]
        }
    }
    
    r = requests.post(FEISHU_WEBHOOK, json=card_payload, timeout=20)
    print(f"飞书 API 返回结果: {r.text}")

if __name__ == "__main__":
    try:
        u, f, q = get_stats_perfectly()
        push_feishu(u, f, q)
    except Exception as e:
        print(f"❌ 运行报错: {e}")
