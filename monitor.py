name: 🔮 Zen Tarot Feishu Bot

on:
  schedule:
    - cron: '0 * * * *' # 每小时自动运行
  workflow_dispatch:   # 支持手动点击运行

jobs:
  run-bot:
    runs-on: ubuntu-latest
    steps:
      - name: ⬇️ 检出代码
        uses: actions/checkout@v4

      - name: 🐍 配置 Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: 📦 安装必要依赖
        run: pip install requests supabase

      - name: 🚀 执行监控并推送
        env:
          SUPABASE_KEY: ${{ secrets.SUPABASE_KEY }}
        run: python monitor.py
