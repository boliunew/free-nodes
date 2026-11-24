#!/usr/bin/env python3
"""
📺 YouTube 节点爬虫（不需要 API Key）

youtube.txt 每行一个：频道链接（/@xxx、/channel/UCxxx）、视频链接、播放列表链接都行
  → 自动解析出频道 ID → 读频道 RSS（含最新视频的完整简介）
  → 从简介里抠出节点分享链接 + 订阅链接 → 抓订阅（简介里给的是网页的话再往下挖一层）
"""
import concurrent.futures as cf, gzip, html, io, os, re, urllib.parse as up, urllib.request as ur, zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
BROWSER = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36",
           "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8", "Cookie": "CONSENT=YES+1"}
SHARE_RE = re.compile(r"(?:vmess|vless|trojan|ss|ssr|hysteria2|hy2|tuic)://[^\s<>\"'`]+")
URL_RE = re.compile(r"https?://[^\s<>\"'`)）]+")
# 看起来像订阅的链接
SUB_HINT = re.compile(r"(\.ya?ml|\.txt|/sub|subscribe|clash|v2ray|nodes?|token=|/link/|raw\.githubusercontent|gist\.github|/api/v1/client|drive\.usercontent|t\.me/s/)", re.I)
# 明显不是订阅的
SKIP = re.compile(r"(youtube\.com|youtu\.be|//(?:www\.)?google\.com|telegram\.org|//(?:www\.)?(?:twitter|x)\.com|facebook|instagram|tiktok|bilibili|"
                  r"patreon|paypal|discord|apps\.apple|play\.google|\.(png|jpe?g|gif|mp4|apk|exe|zip|dmg)$)", re.I)
MAX_VIDEOS = int(os.getenv("YT_MAX_VIDEOS", 5))      # 每个频道看最新几条视频
MAX_URLS = int(os.getenv("YT_MAX_URLS", 60))         # 每次最多跟进多少个链接


def unpack(raw):
    """📦 自动解压：zip 里的文本文件全部拼起来；gzip 直接解；普通文本原样返回"""
    if raw[:2] == b"PK":
        out = []
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                for info in z.infolist():
                    if info.is_dir() or info.file_size > 20_000_000:
                        continue
                    if info.flag_bits & 0x1:  # 加密的压缩包，没密码打不开
                        print(f"    🔒 压缩包加密：{info.filename}")
                        continue
                    data = z.read(info)
                    for enc in ("utf-8", "gbk", "utf-16"):
                        try:
                            out.append(data.decode(enc)); break
                        except UnicodeDecodeError:
                            pass
        except zipfile.BadZipFile:
            return ""
        return "\n".join(out)
    if raw[:2] == b"\x1f\x8b":
        try:
            raw = gzip.decompress(raw)
        except Exception:
            return ""
    for enc in ("utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", "ignore")


def get(url, timeout=25):
    try:
        with ur.urlopen(ur.Request(url, headers=BROWSER), timeout=timeout) as r:
            return unpack(r.read(30_000_000))
    except Exception:
        return ""


def channel_id(entry):
    m = re.search(r"(UC[\w-]{22})", entry)
    if m and "/channel/" in entry:
        return m.group(1)
    page = get_retry(entry if entry.startswith("http") else "https://www.youtube.com/" + entry.lstrip("/"), must="UC")
    for pat in (r'"externalId":"(UC[\w-]{22})"', r'<meta itemprop="channelId" content="(UC[\w-]{22})"',
                r'"channelId":"(UC[\w-]{22})"', r'"browseId":"(UC[\w-]{22})"'):
        m = re.search(pat, page)
        if m:
            return m.group(1)
    return None


def get_retry(url, tries=4, must=None):
    """YouTube 偶尔对 GitHub 服务器抽风，多试几次"""
    import time
    for i in range(tries):
        t = get(url)
        if t and (must is None or must in t):
            return t
        time.sleep(3 * (i + 1))
    return ""


def channel_feed(cid):
    """返回 [(频道名, 视频标题, 简介)]，最新在前"""
    x = get_retry(f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}", must="<entry>")
    if not x:
        return []
    author = html.unescape((re.search(r"<author>\s*<name>(.*?)</name>", x, re.S) or [None, cid])[1])
    out = []
    for e in re.findall(r"<entry>(.*?)</entry>", x, re.S)[:MAX_VIDEOS]:
        title = html.unescape((re.search(r"<title>(.*?)</title>", e, re.S) or [None, ""])[1])
        desc = html.unescape((re.search(r"<media:description>(.*?)</media:description>", e, re.S) or [None, ""])[1])
        out.append((author, title, desc))
    return out


DRIVE_RE = re.compile(r"drive\.google\.com/(?:file/d/|open\?id=|uc\?(?:export=download&)?id=)([\w-]{20,})")
TG_RE = re.compile(r"^https?://t\.me/(?:s/)?([A-Za-z][\w]{3,})/?(?:\d+)?$")


def clean_url(u):
    u = html.unescape(u.rstrip(".,;:!?。，；"))
    if "youtube.com/redirect" in u:  # YouTube 跳转链接解包
        q = up.parse_qs(up.urlparse(u).query).get("q")
        if q:
            u = q[0]
    m = DRIVE_RE.search(u)  # 📁 Google Drive 分享页 → 直接下载地址
    if m:
        return f"https://drive.usercontent.google.com/download?id={m.group(1)}&export=download&confirm=t"
    m = TG_RE.match(u)      # ✈️ Telegram 公开频道 → 网页预览版（不用登录就能看最近的消息）
    if m and m.group(1).lower() not in ("joinchat", "share", "addstickers", "proxy", "socks"):
        return f"https://t.me/s/{m.group(1)}"
    return u


def harvest(text):
    """从一段文字里拿出：分享链接列表、候选订阅 URL 列表"""
    shares = SHARE_RE.findall(text)
    urls = []
    for u in URL_RE.findall(text):
        u = clean_url(u)
        if (u.startswith("https://t.me/") and "/s/" not in u) or "drive.google.com/drive/folders" in u:
            continue  # 私有群邀请链接、网盘文件夹：拿不到内容
        if not SKIP.search(u) and u not in urls:
            urls.append(u)
    # 像订阅的排前面
    urls.sort(key=lambda u: 0 if SUB_HINT.search(u) else 1)
    return shares, urls


CACHE = os.path.join(ROOT, "cache", "youtube.yaml")
CACHE_DAYS = 10  # 一周跑一次，缓存要能撑过一周


def collect(parse_any, parse_links):
    """带兜底：这次一个都没抓到，就用最近一次成功的结果（3 天内）"""
    import time, yaml
    nodes, stats = _collect(parse_any, parse_links)
    if nodes:
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        with open(CACHE, "w", encoding="utf-8") as f:
            yaml.safe_dump({"saved": int(time.time()), "proxies": nodes}, f, allow_unicode=True, sort_keys=False)
        return nodes, stats
    try:
        d = yaml.safe_load(open(CACHE, encoding="utf-8"))
        age = (time.time() - d["saved"]) / 86400
        if age <= CACHE_DAYS:
            print(f"📺 本次没抓到，改用 {age:.1f} 天前的缓存：{len(d['proxies'])} 个")
            stats["from_cache"] = round(age, 1)
            stats["nodes"] = len(d["proxies"])
            return d["proxies"], stats
        print(f"📺 缓存已过期（{age:.1f} 天），不使用")
    except Exception:
        pass
    return nodes, stats


def _collect(parse_any, parse_links):
    """主入口：返回 (节点列表, 统计信息)。parse_any / parse_links 由 collector.py 传入"""
    path = os.path.join(ROOT, "youtube.txt")
    if not os.path.exists(path):
        return [], {}
    entries = [l.strip() for l in open(path, encoding="utf-8") if l.strip() and not l.strip().startswith("#")]
    if not entries:
        return [], {}
    print(f"📺 YouTube：{len(entries)} 个入口")

    with cf.ThreadPoolExecutor(8) as ex:
        cids = list(dict.fromkeys(c for c in ex.map(channel_id, entries) if c))
    print(f"  解析出 {len(cids)} 个频道")
    with cf.ThreadPoolExecutor(8) as ex:
        feeds = list(ex.map(channel_feed, cids))

    nodes, stats, all_urls = [], {"channels": []}, []
    for cid, items in zip(cids, feeds):
        name = items[0][0] if items else cid
        ch_shares, ch_urls = [], []
        for _, title, desc in items:
            s, u = harvest(desc)
            ch_shares += s; ch_urls += u
        got = parse_links("\n".join(ch_shares))
        nodes += got
        all_urls += [(name, u) for u in ch_urls]
        stats["channels"].append({"channel": name, "id": cid, "videos": len(items),
                                  "share_nodes": len(got), "links": len(ch_urls),
                                  "latest": items[0][1][:60] if items else ""})
        print(f"  📺 {name[:30]:30s} 视频 {len(items)} · 直接节点 {len(got)} · 链接 {len(ch_urls)}")

    # 跟进链接：是订阅就直接解析；是网页就再挖一层
    seen, todo = set(), []
    for name, u in all_urls:
        if u not in seen:
            seen.add(u); todo.append((name, u))
    todo = todo[:MAX_URLS]

    def follow(item):
        name, u = item
        text = get(u)
        got = parse_any(text) if text else []
        if got or not text:
            return name, u, got, []
        s, deeper = harvest(text)  # 网页：页面里的分享链接 + 像订阅的链接
        got = parse_links("\n".join(s))
        return name, u, got, [d for d in deeper if SUB_HINT.search(d)][:5]

    second = []
    with cf.ThreadPoolExecutor(12) as ex:
        for name, u, got, deeper in ex.map(follow, todo):
            if got:
                print(f"    ✓ {len(got):4d}  {u[:80]}")
                stats.setdefault("subs", []).append({"channel": name, "url": u, "nodes": len(got)})
            nodes += got
            second += [(name, d) for d in deeper if d not in seen]
    second = list(dict.fromkeys(second))[:MAX_URLS]
    with cf.ThreadPoolExecutor(12) as ex:
        for (name, u), text in zip(second, ex.map(lambda x: get(x[1]), second)):
            got = parse_any(text) if text else []
            if got:
                print(f"    ✓ {len(got):4d}  {u[:80]}  (二层)")
                stats.setdefault("subs", []).append({"channel": name, "url": u, "nodes": len(got)})
                nodes += got
    print(f"📺 YouTube 共拿到 {len(nodes)} 个节点")
    stats["nodes"] = len(nodes)
    return nodes, stats
