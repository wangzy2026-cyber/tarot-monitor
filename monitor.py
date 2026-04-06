def get_stats():
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    # 1. 获取北京时间当前的 0 点
    now_bj = datetime.now(BEIJING_TZ)
    today_bj_00 = now_bj.replace(hour=0, minute=0, second=0, microsecond=0)
    
    # 2. 关键：将北京 0 点转换为对应的 UTC 时间，去数据库里查
    # 比如北京 4月6日 00:00 -> 对应 UTC 4月5日 16:00
    start_time_utc = today_bj_00.astimezone(timezone.utc).isoformat()
    
    print(f"当前北京时间: {now_bj}")
    print(f"统计起始时间 (UTC): {start_time_utc}")
    
    # 查询今日数据
    res = supabase.table("tarot_history").select("anonymous_id").gte("created_at", start_time_utc).execute()
    data = res.data or []
    total_flips = len(data)
    uv = len(set(row['anonymous_id'] for row in data))
    
    # 获取最新提问 (逻辑保持不变)
    q_res = supabase.table("tarot_history").select("question, created_at").not_.is_("question", "null").order("created_at", desc=True).limit(200).execute()
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
