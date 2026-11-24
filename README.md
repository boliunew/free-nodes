# 🛰️ Free Nodes · 全球免费节点自动收集

每周自动从 GitHub 公开节点池 + 📺 YouTube 节点频道抓取 → 用 **mihomo 内核真实测速** → 只留下能用的、最快的 → 生成两份 Clash Meta 订阅：**海外版**（排除美国）和**全部版**。

## 📲 订阅地址

| 用途 | 链接 |
|---|---|
| 🌏 **海外版**（排除美国，亚洲保底 + 欧洲等，最多 200 个） | `https://raw.githubusercontent.com/boliunew/free-nodes/main/output/global.yaml` |
| 📦 **全部版**（美国 100 + 亚洲保底 + 欧洲等，最多 300 个） | `https://raw.githubusercontent.com/boliunew/free-nodes/main/output/clash.yaml` |
| 🧩 只要节点（proxy-provider） | `.../output/global-provider.yaml` · `.../output/provider.yaml` |
| 🚀 jsDelivr 镜像（raw 打不开时用） | `https://testingcf.jsdelivr.net/gh/boliunew/free-nodes@main/output/clash.yaml` |
| 📊 本次统计 | [output/stats.json](output/stats.json) |

## 📱 手机上怎么用（Clash Meta for Android）

1. **配置** → 右上角 **＋** → **URL**
2. 名称随便填，URL 粘贴上面的海外版或全部版链接（两个都加也行，随时切换）
3. **自动更新** 填 `360`（分钟）→ 保存 → 选中这个配置
4. 回首页点 **已停止** 启动 → **代理** 页里默认走「♻️ 自动选择」，会自己挑最快的

## 🗂️ 分组说明

- 🚀 **节点选择**：总开关，可手动选
- ♻️ **自动选择**：每 5 分钟测一次，自动用最快的
- 🔯 **故障转移**：当前挂了自动切下一个
- 🇭🇰🇯🇵🇸🇬🇹🇼🇰🇷🇨🇦🇪🇺🌏 **地区组**：只用某个地区（只显示有节点的地区）
- 🎯 **全球直连** / 🐟 **漏网之鱼**：国内直连、其余走代理

## ⚙️ 调整

- 加/删来源：编辑 `sources.txt`（保存后会自动跑一次）
- 📺 加 YouTube 频道：编辑 `youtube.txt`，贴频道或任意一个视频链接就行，会自动跟踪该频道最新视频简介里的节点
- 更新频率（默认每周日一次）：`.github/workflows/update.yml` 里的 `cron`
- 保留数量 / 延迟上限 / 美国名额：同文件里的 `MAX_NODES`、`MAX_DELAY`、`US_CAP`
- 立即更新：仓库 **Actions** → **🛰️ 更新免费节点** → **Run workflow**

## 📬 Telegram 推送（可选）

仓库 **Settings → Secrets and variables → Actions** 添加：
- `TG_BOT_TOKEN`：找 @BotFather 建一个机器人拿到的 token
- `TG_CHAT_ID`：给机器人发条消息后，访问 `https://api.telegram.org/bot<TOKEN>/getUpdates` 看 `chat.id`

每次更新完会推送：可用数量、最快延迟、国家分布、Top 5 节点。

## ⚠️ 注意

免费节点由陌生人运营，**对方能看到你未加密的流量**。看视频、查资料没问题；**网银、支付、重要账号登录请关掉代理或走直连**。
