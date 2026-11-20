#!/usr/bin/env python3
"""🔬 YouTube 诊断：打印每个频道最新视频简介里的链接，以及每个链接实际返回了什么"""
import os, re, sys, urllib.request as ur
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import youtube as y, collector as c

entries = [l.strip() for l in open("youtube.txt", encoding="utf-8") if l.strip() and not l.startswith("#")]
for e in entries:
    print("ENTRY", e, "->", y.channel_id(e))

cids = list(dict.fromkeys(x for x in map(y.channel_id, entries) if x))
for cid in cids:
    for author, title, desc in y.channel_feed(cid)[:3]:
        print("\n" + "=" * 80)
        print("CHANNEL", author, "| VIDEO", title)
        print("DESC-HEAD", desc[:600].replace("\n", " ⏎ "))
        shares, urls = y.harvest(desc)
        print("SHARES", len(shares))
        for u in urls[:20]:
            try:
                req = ur.Request(u, headers=y.BROWSER)
                with ur.urlopen(req, timeout=15) as r:
                    body = r.read(400000).decode("utf-8", "ignore")
                    final, ct, code = r.geturl(), r.headers.get("Content-Type", ""), r.status
            except Exception as ex:
                print(f"  URL {u}\n      ERR {ex.__class__.__name__}: {str(ex)[:100]}")
                continue
            nodes = len(c.parse_any(body))
            inner = y.SHARE_RE.findall(body)
            subs = [x for x in y.URL_RE.findall(body) if y.SUB_HINT.search(x) and not y.SKIP.search(x)][:6]
            title_m = re.search(r"<title>(.*?)</title>", body, re.S)
            print(f"  URL {u}\n      -> {code} {final[:100]} | {ct[:30]} | {len(body)}B | nodes={nodes} shares_in_page={len(inner)}"
                  f" | title={(title_m.group(1).strip()[:60] if title_m else '')}")
            for s in subs:
                print("      sub?", s[:120])
            if not nodes and not inner:
                txt = re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", body, flags=re.S)
                print("      TEXT", re.sub(r"\s+", " ", txt)[:300])

print("\n" + "#" * 80 + "\n完整流程：")
nodes, st = y.collect(c.parse_any, c.parse_links)
print("TOTAL", len(nodes), st.get("subs"))
