#!/usr/bin/env python3
"""
🛰️ 全球免费节点收集器 —— 给 Clash Meta for Android (mihomo 内核) 用

流程：抓取 sources.txt 里的订阅 → 解析各种格式 → 去重 → 用 mihomo 真实测速
     → 剔除死节点、按延迟排序 → 识别国家 → 生成 output/ 下的订阅文件

用法：
  python collector.py                  # 完整流程（需要 ./mihomo 可执行文件）
  python collector.py --no-test        # 只收集不测速（本地调试用）
  python collector.py --max 150        # 最终保留的节点数
"""
import argparse, base64, concurrent.futures as cf, json, os, random, re, socket, subprocess, sys, time
import urllib.parse as up
import urllib.request as ur
from datetime import datetime, timezone

import yaml

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "output")
UA = {"User-Agent": "clash.meta/1.19 (free-nodes collector)"}
TEST_URL = "https://www.gstatic.com/generate_204"
SUPPORTED = {"ss", "ssr", "vmess", "vless", "trojan", "hysteria", "hysteria2", "tuic", "wireguard", "anytls"}

# ─────────────────────────── 抓取 ───────────────────────────
def fetch(url, timeout=25):
    try:
        req = ur.Request(url, headers=UA)
        with ur.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "ignore")
    except Exception as e:
        print(f"  ✗ {url[:80]}  ({e.__class__.__name__})")
        return ""

def b64d(s):
    s = s.strip().replace("-", "+").replace("_", "/")
    s += "=" * (-len(s) % 4)
    return base64.b64decode(s).decode("utf-8", "ignore")

# ─────────────────────────── 分享链接解析 ───────────────────────────
def _q(u):
    return {k: v[0] for k, v in up.parse_qs(u.query).items()}

def _name(u, fallback):
    return up.unquote(u.fragment).strip() or fallback

def _transport(p, net, q, host_key="host", path_key="path"):
    net = (net or "tcp").lower()
    if net in ("ws", "httpupgrade"):
        p["network"] = "ws"
        o = {"path": q.get(path_key) or "/"}
        if q.get(host_key):
            o["headers"] = {"Host": q[host_key]}
        if net == "httpupgrade":
            o["v2ray-http-upgrade"] = True
        p["ws-opts"] = o
    elif net == "grpc":
        p["network"] = "grpc"
        p["grpc-opts"] = {"grpc-service-name": q.get("serviceName") or q.get(path_key) or ""}
    elif net in ("h2", "http"):
        p["network"] = "h2"
        p["h2-opts"] = {"path": q.get(path_key) or "/", **({"host": [q[host_key]]} if q.get(host_key) else {})}
    elif net == "tcp":
        p["network"] = "tcp"
    else:
        return False  # xhttp/kcp/quic 等 mihomo 不支持
    return True

def parse_vmess(link):
    j = json.loads(b64d(link[8:]))
    p = {"name": j.get("ps") or "vmess", "type": "vmess", "server": j["add"], "port": int(j["port"]),
         "uuid": j["id"], "alterId": int(j.get("aid") or 0), "cipher": j.get("scy") or "auto", "udp": True}
    if str(j.get("tls", "")).lower() == "tls":
        p["tls"] = True
        p["skip-cert-verify"] = True
        if j.get("sni"): p["servername"] = j["sni"]
    q = {"host": j.get("host", ""), "path": j.get("path", ""), "serviceName": j.get("path", "")}
    return p if _transport(p, j.get("net"), q) else None

def parse_vless_trojan(link, kind):
    u = up.urlparse(link); q = _q(u)
    p = {"name": _name(u, kind), "type": kind, "server": u.hostname, "port": int(u.port), "udp": True}
    if kind == "vless":
        p["uuid"] = up.unquote(u.username)
        if q.get("flow"): p["flow"] = q["flow"]
    else:
        p["password"] = up.unquote(u.username)
    sec = q.get("security", "tls" if kind == "trojan" else "none")
    if sec in ("tls", "reality", "xtls"):
        if kind == "vless": p["tls"] = True
        sni = q.get("sni") or q.get("peer")
        if sni: p["servername" if kind == "vless" else "sni"] = sni
        if q.get("fp"): p["client-fingerprint"] = q["fp"]
        p["skip-cert-verify"] = q.get("allowInsecure", "0") in ("1", "true") or sec == "tls"
        if sec == "reality":
            if not q.get("pbk"): return None
            p["reality-opts"] = {"public-key": q["pbk"], **({"short-id": q["sid"]} if q.get("sid") else {})}
            p["client-fingerprint"] = q.get("fp") or "chrome"
    return p if _transport(p, q.get("type"), q) else None

def parse_ss(link):
    body = link[5:]
    name = up.unquote(body.split("#", 1)[1]) if "#" in body else "ss"
    body = body.split("#", 1)[0]
    plugin = None
    if "?" in body:
        body, qs = body.split("?", 1)
        plugin = up.parse_qs(qs).get("plugin", [None])[0]
    body = body.rstrip("/")
    if "@" in body:
        userinfo, hostport = body.rsplit("@", 1)
        userinfo = up.unquote(userinfo)
        if ":" not in userinfo:
            userinfo = b64d(userinfo)
    else:
        userinfo, hostport = b64d(body).rsplit("@", 1)
    method, pw = userinfo.split(":", 1)
    host, port = hostport.rsplit(":", 1)
    p = {"name": name, "type": "ss", "server": host.strip("[]"), "port": int(port),
         "cipher": method, "password": pw, "udp": True}
    if plugin:
        parts = up.unquote(plugin).split(";")
        if parts[0] in ("obfs-local", "simple-obfs"):
            opt = dict(x.split("=", 1) for x in parts[1:] if "=" in x)
            p["plugin"] = "obfs"
            p["plugin-opts"] = {"mode": opt.get("obfs", "http"), "host": opt.get("obfs-host", "bing.com")}
        elif parts[0] == "v2ray-plugin":
            p["plugin"] = "v2ray-plugin"
            p["plugin-opts"] = {"mode": "websocket", "tls": "tls" in parts}
        else:
            return None
    return p

def parse_hy2(link):
    u = up.urlparse(link); q = _q(u)
    pw = up.unquote(u.username or "") + (":" + up.unquote(u.password) if u.password else "")
    p = {"name": _name(u, "hy2"), "type": "hysteria2", "server": u.hostname, "port": int(u.port or 443),
         "password": pw, "skip-cert-verify": q.get("insecure", "0") in ("1", "true"), "udp": True}
    if q.get("sni"): p["sni"] = q["sni"]
    if q.get("obfs"):
        p["obfs"] = q["obfs"]; p["obfs-password"] = q.get("obfs-password", "")
    return p

def parse_tuic(link):
    u = up.urlparse(link); q = _q(u)
    p = {"name": _name(u, "tuic"), "type": "tuic", "server": u.hostname, "port": int(u.port),
         "uuid": up.unquote(u.username), "password": up.unquote(u.password or ""),
         "congestion-controller": q.get("congestion_control", "bbr"),
         "alpn": (q.get("alpn") or "h3").split(","), "skip-cert-verify": True, "udp-relay-mode": q.get("udp_relay_mode", "native")}
    if q.get("sni"): p["sni"] = q["sni"]
    return p

PARSERS = {"vmess://": parse_vmess, "vless://": lambda l: parse_vless_trojan(l, "vless"),
           "trojan://": lambda l: parse_vless_trojan(l, "trojan"), "ss://": parse_ss,
           "hysteria2://": parse_hy2, "hy2://": parse_hy2, "tuic://": parse_tuic}

def parse_links(text):
    out = []
    for line in text.splitlines():
        line = line.strip()
        for pre, fn in PARSERS.items():
            if line.startswith(pre):
                try:
                    p = fn(line)
                    if p and p.get("server") and p.get("port"): out.append(p)
                except Exception:
                    pass
                break
    return out

def parse_any(text):
    t = text.strip()
    if not t: return []
    if "proxies:" in t[:5000] or t.startswith("- {") or "\nproxies:" in t:
        try:
            d = yaml.safe_load(t)
            items = d.get("proxies") if isinstance(d, dict) else d
            return [p for p in (items or []) if isinstance(p, dict)]
        except Exception:
            pass
    if "://" not in t[:200]:
        try:
            t = b64d(re.sub(r"\s+", "", t))
        except Exception:
            return []
    return parse_links(t)

# ─────────────────────────── 清洗去重 ───────────────────────────
REQUIRED = {"ss": ["cipher", "password"], "vmess": ["uuid"], "vless": ["uuid"], "trojan": ["password"],
            "hysteria2": ["password"], "tuic": ["uuid"], "ssr": ["cipher", "password", "obfs", "protocol"]}
BAD_SS = {"rc4", "rc4-md5", "none", "table", "plain"}

def clean(proxies):
    seen, out = set(), []
    for p in proxies:
        try:
            t = str(p.get("type", "")).lower()
            if t not in SUPPORTED: continue
            if any(not p.get(k) for k in REQUIRED.get(t, [])): continue
            srv = str(p.get("server", "")).strip()
            port = int(p.get("port", 0))
            if not srv or not (0 < port < 65536) or srv.startswith(("127.", "0.", "10.", "192.168.")) or srv == "localhost":
                continue
            if t == "ss" and str(p.get("cipher", "")).lower() in BAD_SS: continue
            if t == "vless" and p.get("flow") and "vision" not in str(p["flow"]): p.pop("flow")
            key = (t, srv.lower(), port, str(p.get("uuid") or p.get("password") or ""),
                   str(p.get("network", "")), str((p.get("ws-opts") or {}).get("path", "")))
            if key in seen: continue
            seen.add(key)
            p = {k: v for k, v in p.items() if v is not None}
            p["server"], p["port"], p["type"] = srv, port, t
            p["name"] = str(p.get("name") or t)
            out.append(p)
        except Exception:
            continue
    return out

def unique_names(proxies):
    used = {}
    for i, p in enumerate(proxies):
        p["name"] = f"n{i:05d}"  # 测速阶段用中性名字，避免奇怪字符
        used[p["name"]] = p
    return proxies

# ─────────────────────────── mihomo 测速 ───────────────────────────
def mihomo_bin():
    for c in ("./mihomo", os.path.join(ROOT, "mihomo"), "mihomo"):
        try:
            subprocess.run([c, "-v"], capture_output=True, timeout=10); return c
        except Exception:
            pass
    sys.exit("❌ 找不到 mihomo 可执行文件")

def write_test_config(proxies, path, port):
    cfg = {"mixed-port": 0, "allow-lan": False, "mode": "global", "log-level": "silent",
           "external-controller": f"127.0.0.1:{port}", "ipv6": False,
           "dns": {"enable": True, "ipv6": False, "nameserver": ["1.1.1.1", "8.8.8.8"]},
           "proxies": proxies}
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)

def prune_invalid(proxies, mh, workdir):
    """mihomo 遇到一个坏节点整个配置都起不来 → 反复 -t 校验，按报错的序号剔除"""
    path = os.path.join(workdir, "check.yaml")
    for _ in range(1500):
        write_test_config(proxies, path, 9090)
        r = subprocess.run([mh, "-t", "-d", workdir, "-f", path], capture_output=True, text=True, timeout=120)
        msg = r.stdout + r.stderr
        if r.returncode == 0 and "successful" in msg.lower():
            return proxies
        m = re.search(r"proxy (\d+)", msg)
        if not m:
            print("  ⚠️ 校验失败但无法定位：", msg[-300:]); return proxies
        bad = int(m.group(1))
        proxies = proxies[:bad] + proxies[bad + 1:]
    return proxies

def delay_test(proxies, mh, workdir, timeout_ms=5000, workers=96, rounds=2):
    port = random.randint(20000, 40000)
    path = os.path.join(workdir, "run.yaml")
    write_test_config(proxies, path, port)
    proc = subprocess.Popen([mh, "-d", workdir, "-f", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    api = f"http://127.0.0.1:{port}"
    opener = ur.build_opener(ur.ProxyHandler({}))
    try:
        for _ in range(60):
            try:
                opener.open(api + "/version", timeout=1); break
            except Exception:
                time.sleep(0.5)

        def one(name):
            url = f"{api}/proxies/{up.quote(name)}/delay?timeout={timeout_ms}&url={up.quote(TEST_URL)}"
            try:
                return name, json.loads(opener.open(url, timeout=timeout_ms / 1000 + 5).read()).get("delay")
            except Exception:
                return name, None

        results = {p["name"]: [] for p in proxies}
        names = list(results)
        for r in range(rounds):
            with cf.ThreadPoolExecutor(workers) as ex:
                for name, d in ex.map(one, names):
                    if d: results[name].append(d)
            names = [n for n in names if results[n]]  # 第二轮只复测活着的
            print(f"  第 {r + 1} 轮：存活 {len(names)}")
        return {n: sum(v) / len(v) for n, v in results.items() if len(v) == rounds}
    finally:
        proc.terminate()
        try: proc.wait(10)
        except Exception: proc.kill()

# ─────────────────────────── 国家识别 ───────────────────────────
FLAGS = {"HK": ("🇭🇰", "香港"), "TW": ("🇹🇼", "台湾"), "JP": ("🇯🇵", "日本"), "SG": ("🇸🇬", "新加坡"),
         "KR": ("🇰🇷", "韩国"), "US": ("🇺🇸", "美国"), "CA": ("🇨🇦", "加拿大"), "GB": ("🇬🇧", "英国"),
         "DE": ("🇩🇪", "德国"), "FR": ("🇫🇷", "法国"), "NL": ("🇳🇱", "荷兰"), "RU": ("🇷🇺", "俄罗斯"),
         "TR": ("🇹🇷", "土耳其"), "IN": ("🇮🇳", "印度"), "AU": ("🇦🇺", "澳大利亚"), "FI": ("🇫🇮", "芬兰"),
         "SE": ("🇸🇪", "瑞典"), "PL": ("🇵🇱", "波兰"), "IR": ("🇮🇷", "伊朗"), "AE": ("🇦🇪", "阿联酋"),
         "BR": ("🇧🇷", "巴西"), "VN": ("🇻🇳", "越南"), "TH": ("🇹🇭", "泰国"), "MY": ("🇲🇾", "马来西亚"),
         "ID": ("🇮🇩", "印尼"), "PH": ("🇵🇭", "菲律宾"), "IT": ("🇮🇹", "意大利"), "ES": ("🇪🇸", "西班牙"),
         "CH": ("🇨🇭", "瑞士"), "UA": ("🇺🇦", "乌克兰"), "LT": ("🇱🇹", "立陶宛"), "CZ": ("🇨🇿", "捷克"),
         "AT": ("🇦🇹", "奥地利"), "RO": ("🇷🇴", "罗马尼亚"), "CN": ("🇨🇳", "中国"), "IE": ("🇮🇪", "爱尔兰"),
         "IL": ("🇮🇱", "以色列"), "MX": ("🇲🇽", "墨西哥"), "AR": ("🇦🇷", "阿根廷"), "ZA": ("🇿🇦", "南非")}

def resolve(host):
    if re.fullmatch(r"[\d.]+|[0-9a-fA-F:]+", host): return host
    try: return socket.gethostbyname(host)
    except Exception: return None

def flag_from_name(name):
    m = re.search(r"([\U0001F1E6-\U0001F1FF]{2})", name)
    if not m: return None
    cc = "".join(chr(ord(c) - 0x1F1E6 + 65) for c in m.group(1))
    return cc

def geo_lookup(proxies):
    """优先用 IP 查国家（ip-api 批量接口），失败则用原名字里的国旗"""
    ips = {}
    with cf.ThreadPoolExecutor(64) as ex:
        for p, ip in zip(proxies, ex.map(lambda p: resolve(p["server"]), proxies)):
            if ip: ips[p["name"]] = ip
    uniq = list(set(ips.values())); cc_of = {}
    for i in range(0, len(uniq), 100):
        try:
            body = json.dumps([{"query": ip, "fields": "query,countryCode"} for ip in uniq[i:i + 100]]).encode()
            req = ur.Request("http://ip-api.com/batch", data=body, headers={"Content-Type": "application/json"})
            for r in json.loads(ur.urlopen(req, timeout=20).read()):
                if r.get("countryCode"): cc_of[r["query"]] = r["countryCode"]
            time.sleep(1.5)
        except Exception as e:
            print("  ⚠️ IP 归属查询失败：", e.__class__.__name__); break
    for p in proxies:
        p["_cc"] = cc_of.get(ips.get(p["name"])) or flag_from_name(p.get("_orig", "")) or "ZZ"

def final_names(proxies):
    count = {}
    for p in proxies:
        cc = p.pop("_cc", "ZZ")
        p.pop("_orig", None)
        flag, cn = FLAGS.get(cc, ("".join(chr(0x1F1E6 + ord(c) - 65) for c in cc), cc) if cc != "ZZ" else ("🌐", "未知"))
        count[cc] = count.get(cc, 0) + 1
        p["name"] = f"{flag} {cn} {count[cc]:02d}"

# ─────────────────────────── 生成配置 ───────────────────────────
REGIONS = [("🇭🇰 香港", "香港|HK|🇭🇰"), ("🇯🇵 日本", "日本|JP|🇯🇵"), ("🇸🇬 新加坡", "新加坡|SG|🇸🇬"),
           ("🇺🇸 美国", "美国|US|🇺🇸"), ("🇹🇼 台湾", "台湾|TW|🇹🇼"), ("🇪🇺 欧洲", "🇩🇪|🇬🇧|🇫🇷|🇳🇱|🇫🇮|🇸🇪|🇵🇱|🇮🇹|🇪🇸|🇨🇭|🇦🇹|🇨🇿|🇷🇴|🇱🇹|🇮🇪")]

def build_config(proxies):
    names = [p["name"] for p in proxies]
    regions = [(g, [n for n in names if re.search(rx, n)]) for g, rx in REGIONS]
    regions = [(g, ns) for g, ns in regions if ns]
    test = {"url": TEST_URL, "interval": 300, "tolerance": 50, "lazy": True}
    groups = [
        {"name": "🚀 节点选择", "type": "select", "proxies": ["♻️ 自动选择", "🔯 故障转移", *[g for g, _ in regions], "DIRECT", *names]},
        {"name": "♻️ 自动选择", "type": "url-test", "proxies": names, **test},
        {"name": "🔯 故障转移", "type": "fallback", "proxies": names[:60], **test},
        *[{"name": g, "type": "url-test", "proxies": ns, **test} for g, ns in regions],
        {"name": "🎯 全球直连", "type": "select", "proxies": ["DIRECT", "🚀 节点选择"]},
        {"name": "🐟 漏网之鱼", "type": "select", "proxies": ["🚀 节点选择", "DIRECT"]},
    ]
    return {
        "mixed-port": 7890, "allow-lan": False, "mode": "rule", "log-level": "info", "ipv6": False,
        "unified-delay": True, "tcp-concurrent": True,
        "geodata-mode": True, "geo-auto-update": True, "geo-update-interval": 72,
        "geox-url": {"geoip": "https://testingcf.jsdelivr.net/gh/MetaCubeX/meta-rules-dat@release/geoip.dat",
                     "geosite": "https://testingcf.jsdelivr.net/gh/MetaCubeX/meta-rules-dat@release/geosite.dat",
                     "mmdb": "https://testingcf.jsdelivr.net/gh/MetaCubeX/meta-rules-dat@release/country.mmdb"},
        "dns": {"enable": True, "ipv6": False, "enhanced-mode": "fake-ip", "fake-ip-range": "198.18.0.1/16",
                "fake-ip-filter": ["*.lan", "+.local", "+.msftconnecttest.com", "+.msftncsi.com"],
                "default-nameserver": ["223.5.5.5", "1.1.1.1"],
                "nameserver": ["https://1.1.1.1/dns-query", "https://dns.google/dns-query"],
                "proxy-server-nameserver": ["https://223.5.5.5/dns-query", "https://1.1.1.1/dns-query"]},
        "sniffer": {"enable": True, "sniff": {"HTTP": {"ports": [80, "8080-8880"]}, "TLS": {"ports": [443, 8443]}, "QUIC": {"ports": [443]}}},
        "proxies": proxies,
        "proxy-groups": groups,
        "rules": ["GEOSITE,private,DIRECT", "GEOIP,private,DIRECT,no-resolve",
                  "GEOSITE,category-ads-all,REJECT",
                  "GEOSITE,cn,🎯 全球直连", "GEOIP,CN,🎯 全球直连",
                  "MATCH,🐟 漏网之鱼"],
    }

def dump(obj, path):
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(obj, f, allow_unicode=True, sort_keys=False, width=1000)

# ─────────────────────────── 主流程 ───────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=int(os.getenv("MAX_NODES", 200)))
    ap.add_argument("--max-delay", type=int, default=int(os.getenv("MAX_DELAY", 3000)))
    ap.add_argument("--max-candidates", type=int, default=int(os.getenv("MAX_CANDIDATES", 6000)))
    ap.add_argument("--no-test", action="store_true")
    a = ap.parse_args()
    t0 = time.time()
    os.makedirs(OUT, exist_ok=True)
    work = os.path.join(ROOT, ".work"); os.makedirs(work, exist_ok=True)

    srcs = [l.strip() for l in open(os.path.join(ROOT, "sources.txt"), encoding="utf-8")
            if l.strip() and not l.strip().startswith("#")]
    print(f"📡 抓取 {len(srcs)} 个来源…")
    raw, src_stats = [], []
    with cf.ThreadPoolExecutor(12) as ex:
        for url, text in zip(srcs, ex.map(fetch, srcs)):
            got = parse_any(text)
            src_stats.append((url, len(got)))
            print(f"  ✓ {len(got):5d}  {url[:90]}")
            raw += got
    for p in raw: p["_orig"] = str(p.get("name", ""))
    proxies = clean(raw)
    print(f"🧹 原始 {len(raw)} → 去重后 {len(proxies)}")
    random.shuffle(proxies)
    proxies = proxies[:a.max_candidates]
    orig = {}
    for i, p in enumerate(proxies):
        orig[f"n{i:05d}"] = p.pop("_orig", "")
    unique_names(proxies)

    if a.no_test:
        alive = proxies[:a.max]
        delays = {}
    else:
        mh = mihomo_bin()
        print("🔍 校验配置合法性…")
        proxies = prune_invalid(proxies, mh, work)
        print(f"  合法节点 {len(proxies)}")
        print("⚡ 真实测速中（mihomo url-test）…")
        delays = delay_test(proxies, mh, work)
        alive = [p for p in proxies if p["name"] in delays and delays[p["name"]] <= a.max_delay]
        alive.sort(key=lambda p: delays[p["name"]])
        alive = alive[:a.max]
    print(f"✅ 最终保留 {len(alive)} 个节点")
    if not alive:
        sys.exit("❌ 没有可用节点，本次不覆盖旧订阅")

    for p in alive: p["_orig"] = orig.get(p["name"], "")
    dmap = {p["name"]: delays.get(p["name"]) for p in alive}
    print("🌍 识别节点国家…")
    geo_lookup(alive)
    old = [p["name"] for p in alive]
    final_names(alive)
    final_delay = {p["name"]: dmap[o] for p, o in zip(alive, old)}

    dump(build_config(alive), os.path.join(OUT, "clash.yaml"))
    dump({"proxies": alive}, os.path.join(OUT, "provider.yaml"))

    by_cc = {}
    for p in alive:
        k = p["name"].rsplit(" ", 1)[0]; by_cc[k] = by_cc.get(k, 0) + 1
    by_type = {}
    for p in alive: by_type[p["type"]] = by_type.get(p["type"], 0) + 1
    ds = sorted(v for v in final_delay.values() if v)
    stats = {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "candidates": len(proxies), "alive": len(alive),
        "fastest_ms": round(ds[0]) if ds else None, "median_ms": round(ds[len(ds) // 2]) if ds else None,
        "countries": dict(sorted(by_cc.items(), key=lambda x: -x[1])), "protocols": by_type,
        "sources": [{"url": u, "nodes": n} for u, n in src_stats],
        "top10": [{"name": p["name"], "type": p["type"], "delay": round(final_delay[p["name"]] or 0)} for p in alive[:10]],
        "seconds": round(time.time() - t0),
    }
    json.dump(stats, open(os.path.join(OUT, "stats.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"🎉 完成，用时 {stats['seconds']}s")

if __name__ == "__main__":
    main()
