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

def get_stats_via_sql():
    print("--- 正在提取数据 ---")
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    # 逻辑 1: 获取今日 UV 和 占卜次数 (北京时间)
    # 稍微拓宽一下范围，确保包含凌晨数据
    today_bj_str = datetime.now(BEIJING_TZ).strftime('%Y-%m-%d')
    
    # 使用 RPC 或者直接查询并侧端处理
    res = supabase.table("tarot_history").select("anonymous_id, created_at").gte("created_at", (datetime.now(BEIJING_TZ).replace(hour=0,minute=0,second=0)).astimezone(timezone.utc).isoformat()).execute()
    data = res.data or []
    total_flips = len(data)
    uv = len(set(row['anonymous_id'] for row in data))

    # 逻辑 2: 获取最新提问 (严格执行你的 SQL 逻辑：去重 + 排除 NULL + 长度 > 2)
    q_res = supabase.table("tarot_history") \
        .select("question, created_at") \
        .not_.is_("question", "null") \
        .order("created_at", desc=True) \
        .limit(200).execute()
    
    seen_q = set()
    latest_qs = []
    for row in (q_res.data or []):
        q = (row['question'] or "").strip()
        if len(q) > 2 and q not in seen_q:
            seen_q.add(q)
            # 转换时间显示
            utc_dt = datetime.fromisoformat(row['created_at'].replace('Z', '+00:00'))
            bj_time = utc_dt.astimezone(BEIJING_TZ).strftime("%H:%M")
            latest_qs.append(f"[{bj_time}] {q}")
        if len(latest_qs) >= 25: break
            
    return uv, total_flips, latest_qs

def push_feishu(uv, flips, qs):
    print("--- 正在推送飞书 ---")
    now_str = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M")
    q_text = "\n".join(qs) if qs else "今日暂无提问"

    # 结构化 payload，requests.post(json=...) 会自动处理转义
    payload = {
        "msg_type": "interactive",
        "card": {
            "header": {"title": {"tag": "plain_text", "content": "🔮 Zen Tarot 运营看板"}, "template": "purple"},
            "elements": [
                {"tag": "markdown", "content": f"**📊 今日实时数据 (0点起)**\n👤 UV (独立用户)：**{uv}**\n🃏 占卜总次数：**{flips}**\n🕒 时间：{now_str}"},
                {"tag": "hr"},
                {"tag": "markdown", "content": f"**❓ 最新去重提问 (Top 25)**\n{q_text}"},
                {"tag": "note", "content": {"tag": "plain_text", "content": "数据已自动同步 Supabase 最新统计"}}
            ]
        }
    }
    
    r = requests.post(FEISHU_WEBHOOK, json=payload, timeout=10)
    print(f"飞书返回: {r.text}")

if __name__ == "__main__":
    try:
        uv_val, flips_val, qs_val = get_stats_via_sql()
        push_feishu(uv_val, flips_val, qs_val)
    except Exception as e:
        print(f"❌ 程序报错: {e}")
