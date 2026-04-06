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

def run_task():
    print("--- 任务开始 ---")
    if not SUPABASE_KEY:
        print("❌ 错误：环境变量 SUPABASE_KEY 为空")
        return

    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    # --- 精准北京时间今日 0 点计算 ---
    now_bj = datetime.now(BEIJING_TZ)
    # 计算今天凌晨 00:00:00
    today_0am_bj = now_bj.replace(hour=0, minute=0, second=0, microsecond=0)
    # 转换为 UTC 时间戳供数据库查询
    start_time_utc = today_0am_bj.astimezone(timezone.utc).isoformat()
    
    print(f"当前时间 (北京): {now_bj.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"统计起始 (UTC): {start_time_utc}")

    # 1. 查询统计数据
    try:
        res = supabase.table("tarot_history").select("anonymous_id").gte("created_at", start_time_utc).execute()
        data = res.data or []
        total_flips = len(data)
        uv = len(set(row['anonymous_id'] for row in data))
        print(f"✅ 查询成功: UV={uv}, 次数={total_flips}")
    except Exception as e:
        print(f"❌ 查询统计报错: {e}")
        return

    # 2. 查询最新提问
    try:
        q_res = supabase.table("tarot_history")\
            .select("question, created_at")\
            .not_.is_("question", "null")\
            .order("created_at", desc=True)\
            .limit(200).execute()
        
        seen, qs = set(), []
        for row in (q_res.data or []):
            q = (row['question'] or "").strip()
            if len(q) > 2 and q not in seen:
                seen.add(q)
                utc_dt = datetime.fromisoformat(row['created_at'].replace('Z', '+00:00'))
                bj_time = utc_dt.astimezone(BEIJING_TZ).strftime("%H:%M")
                qs.append(f"[{bj_time}] {q}")
            if len(qs) >= 20: break
    except Exception as e:
        print(f"❌ 查询提问报错: {e}")
        qs = ["查询提问失败"]

    # 3. 推送飞书
    print("正在推送飞书...")
    q_text = "\n".join(qs) if qs else "今日暂无有效提问"
    payload = {
        "msg_type": "interactive",
        "card": {
            "header": {"title": {"tag": "plain_text", "content": "🔮 Zen Tarot 运营速报"}, "template": "purple"},
            "body": {"elements": [
                {"tag": "markdown", "content": f"**📊 今日数据 (北京时间 0点起)**\n👤 独立用户 (UV)：**{uv}**\n🃏 翻牌总次数：**{total_flips}**\n🕒 更新于：{now_bj.strftime('%Y-%m-%d %H:%M')}"},
                {"tag": "hr"},
                {"tag": "markdown", "content": f"**❓ 最新提问**\n{q_text}"}
            ]}
        }
    }
    
    try:
        r = requests.post(FEISHU_WEBHOOK, json=payload, timeout=10)
        print(f"飞书返回: {r.text}")
    except Exception as e:
        print(f"❌ 推送飞书失败: {e}")

# --- 关键执行入口 ---
if __name__ == "__main__":
    run_task()
