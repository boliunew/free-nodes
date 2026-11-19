#!/usr/bin/env python3
"""📬 更新完成后推送到 Telegram（可选：没配置 TG_BOT_TOKEN / TG_CHAT_ID 就自动跳过）"""
import json, os, urllib.request as ur

tok, chat = os.getenv("TG_BOT_TOKEN"), os.getenv("TG_CHAT_ID")
if not (tok and chat):
    print("未配置 Telegram，跳过推送"); raise SystemExit

s = json.load(open("output/stats.json", encoding="utf-8"))
repo = os.getenv("GITHUB_REPOSITORY", "")
sub = f"https://raw.githubusercontent.com/{repo}/main/output/clash.yaml"
top_cc = " ".join(f"{k}×{v}" for k, v in list(s["countries"].items())[:8])
top = "\n".join(f"  {i+1}. {t['name']}  {t['type']}  {t['delay']}ms" for i, t in enumerate(s["top5"] if "top5" in s else s["top10"][:5]))
msg = (f"🛰️ 免费节点已更新\n"
       f"🕒 {s['updated']}\n"
       f"✅ 可用 {s['alive']} / 测试 {s['candidates']}\n"
       f"⚡ 最快 {s['fastest_ms']}ms · 中位 {s['median_ms']}ms\n"
       f"🌍 {top_cc}\n\n🏆 最快 5 个：\n{top}\n\n"
       f"📲 订阅：{sub}")
req = ur.Request(f"https://api.telegram.org/bot{tok}/sendMessage",
                 data=json.dumps({"chat_id": chat, "text": msg, "disable_web_page_preview": True}).encode(),
                 headers={"Content-Type": "application/json"})
print(ur.urlopen(req, timeout=20).read()[:200])
