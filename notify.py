#!/usr/bin/env python3
"""📬 更新完成后推送到 Telegram（可选：没配置 TG_BOT_TOKEN / TG_CHAT_ID 就自动跳过）"""
import json, os, urllib.request as ur

tok, chat = os.getenv("TG_BOT_TOKEN"), os.getenv("TG_CHAT_ID")
if not (tok and chat):
    print("未配置 Telegram，跳过推送"); raise SystemExit

s = json.load(open("output/stats.json", encoding="utf-8"))
base = f"https://raw.githubusercontent.com/{os.getenv('GITHUB_REPOSITORY', '')}/main/output"
cc = lambda d: " ".join(f"{k}×{v}" for k, v in list(d.items())[:8])
top = "\n".join(f"  {i+1}. {t['name']}  {t['type']}  {t['delay']}ms" for i, t in enumerate(s.get("global_top10", [])[:5]))
msg = (f"🛰️ 免费节点已更新 · {s['updated']}\n"
       f"✅ 存活 {s.get('alive_total', s['alive'])} / 测试 {s['candidates']}\n\n"
       f"🌏 海外版 {s.get('global_nodes', 0)} 个：{cc(s.get('global_countries', {}))}\n"
       f"🏆 海外最快：\n{top}\n\n"
       f"📦 全部版 {s['alive']} 个 · 最快 {s['fastest_ms']}ms\n\n"
       f"📲 海外订阅：{base}/global.yaml\n📲 全部订阅：{base}/clash.yaml")
req = ur.Request(f"https://api.telegram.org/bot{tok}/sendMessage",
                 data=json.dumps({"chat_id": chat, "text": msg, "disable_web_page_preview": True}).encode(),
                 headers={"Content-Type": "application/json"})
print(ur.urlopen(req, timeout=20).read()[:200])
