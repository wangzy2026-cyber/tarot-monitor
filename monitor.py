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
    
    # 精准计算北京时间今日 0 点
    today_bj_0am = datetime.now(BEIJING_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    start_time_utc = today_bj_0am.astimezone(timezone.utc).isoformat()
    
    # 逻辑 A：总占卜次数 (精准对齐 COUNT(*))
    res_count = supabase.table("tarot_history")\
        .select("created_at", count="exact")\
        .gte("created_at", start_time_utc)\
        .limit(1).execute()
    total_flips = res_count.count if res_count.count is not None else 0

    # 逻辑 B：独立用户数 (使用时间戳游标解决 UUID 报错)
    unique_users = set()
    current_cursor = start_time_utc
    
    while True:
        # 每次拉取 1000 条，按照时间顺序往后推
        r = supabase.table("tarot_history")\
            .select("anonymous_id, created_at")\
            .gte("created_at", current_cursor)\
            .order("created_at", desc=False)\
            .limit(1000).execute()
        
        batch = r.data or []
        if not batch: break
        
        for row in batch:
            unique_users.add(row['anonymous_id'])
        
        # 如果这一页满了，把游标更新为本页最后一条记录的时间戳
        if len(batch) < 1000:
            break
        
        # 这里的微调是为了防止时间戳完全一致导致死循环，取最后一条时间并略微增加
        last_time = batch[-1]['created_at']
        current_cursor = last_time
        # 防止完全相同的时间戳导致死循环，我们通过逻辑判断跳出
        if len(unique_users) > 50000: break # 安全阀

    uv = len(unique_users)
    print(f"✅ 最终核对：UV={uv}, Flips={total_flips}")

    # 逻辑 C：最新提问 (Top 15)
    q_res = supabase.table("tarot_history")\
        .select("question, created_at")\
        .not_.is_("question", "null")\
        .order("created_at", desc=True)\
        .limit(100).execute()
    
    qs = []
    seen = set()
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
    # 构建飞书卡片
    card = {
        "msg_type": "interactive",
        "card": {
            "header": {"title": {"tag": "plain_text", "content": "🔮 Zen Tarot 运营看板"}, "template": "purple"},
            "elements": [
                {"tag": "markdown", "content": f"**📅 统计日期：** {datetime.now(BEIJING_TZ).strftime('%Y-%m-%d')}\n👤 独立用户 (UV)：**{uv}**\n🃏 占卜总次数：**{flips:,}**"},
                {"tag": "hr"},
                {"tag": "markdown", "content": f"**❓ 最新提问 (Top 15)**\n" + ("\n".join(qs) if qs else "暂无数据")}
            ]
        }
    }
    r = requests.post(FEISHU_WEBHOOK, json=card, timeout=15)
    print(f"飞书返回: {r.text}")

if __name__ == "__main__":
    try:
        u, f, q = get_stats()
        push_feishu(u, f, q)
    except Exception as e:
        print(f"❌ 最终运行失败: {e}")
