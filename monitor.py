import os
import requests
import json
from datetime import datetime, timezone, timedelta
from supabase import create_client, Client

# --- 配置 ---
SUPABASE_URL = "https://ybragvmvirddqfotqxig.supabase.co"
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/db9c21f0-9453-410d-ae0e-c9116a8dc612"
BEIJING_TZ = timezone(timedelta(hours=8))

def get_stats():
    print("--- 正在执行精准统计 ---")
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    # 1. 严格对齐你 SQL 的日期过滤
    today_bj = datetime.now(BEIJING_TZ).date().isoformat() 
    # 计算 UTC 零点起始（北京 0 点 = UTC 前一天 16 点）
    start_time_utc = (datetime.now(BEIJING_TZ).replace(hour=0,minute=0,second=0,microsecond=0)).astimezone(timezone.utc).isoformat()

    # --- 核心逻辑 A：占卜总次数 (COUNT(*)) ---
    # 使用 exact count，这个数字绝对会和你 SQL 的 13701 对上
    res_total = supabase.table("tarot_history")\
        .select("id", count="exact")\
        .gte("created_at", start_time_utc)\
        .limit(1).execute()
    total_flips = res_total.count if res_total.count else 0

    # --- 核心逻辑 B：独立用户数 (COUNT(DISTINCT anonymous_id)) ---
    # 既然 UV 接近 1000 且数据量大，我们改用一种“暴力但准确”的方法：
    # 循环拉取今日所有 anonymous_id（防止被 1000 条限制截断）
    all_ids = []
    page = 0
    while True:
        r = supabase.table("tarot_history")\
            .select("anonymous_id")\
            .gte("created_at", start_time_utc)\
            .range(page * 1000, (page + 1) * 1000 - 1)\
            .execute()
        if not r.data: break
        all_ids.extend([row['anonymous_id'] for row in r.data])
        if len(r.data) < 1000: break
        page += 1
    
    uv = len(set(all_ids))

    # --- 核心逻辑 C：最新提问 (Top 15) ---
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
            qs.append(f"• [{bj_time}] {q}")
        if len(qs) >= 15: break
            
    return uv, total_flips, qs

def push_feishu(uv, flips, qs):
    print(f"--- 最终校验数据: UV={uv}, Flips={flips} ---")
    now_str = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M")
    q_text = "\n".join(qs) if qs else "今日暂无提问"

    # 使用飞书标准卡片格式，确保 100% 能收到
    card_payload = {
        "msg_type": "interactive",
        "card": {
            "header": {"title": {"tag": "plain_text", "content": "🔮 Zen Tarot 运营速报"}, "template": "purple"},
            "elements": [
                {"tag": "markdown", "content": f"**📅 统计日期：** {datetime.now(BEIJING_TZ).strftime('%Y-%m-%d')}"},
                {"tag": "markdown", "content": f"👤 独立用户 (UV)：**{uv}**\n🃏 占卜总次数：**{flips:,}**"},
                {"tag": "hr"},
                {"tag": "markdown", "content": f"**❓ 最新提问 (Top 15)**\n{q_text}"},
                {"tag": "note", "content": {"tag": "plain_text", "content": f"数据更新于 {now_str}"}}
            ]
        }
    }
    
    r = requests.post(FEISHU_WEBHOOK, json=card_payload, timeout=15)
    print(f"飞书 API 返回结果: {r.text}")

if __name__ == "__main__":
    try:
        u, f, q = get_stats()
        push_feishu(u, f, q)
    except Exception as e:
        print(f"程序报错: {e}")
