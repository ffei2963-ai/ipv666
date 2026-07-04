# IPv666 — IPv6 多协议代理站群管理器

[![Python](https://img.shields.io/badge/Python-3.10+-green)](https://www.python.org/)
[![Xray](https://img.shields.io/badge/Xray-1.8.23-orange)](https://github.com/XTLS/Xray-core)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

将一台仅有 **单个 IPv6 地址** 的 VPS 变成可动态创建/管理**数万个 IPv6 代理**的站群服务器。集成 **Ollama AI（qwen2:0.5b）**，通过 **Telegram Bot + Inline Keyboard** 实现对话式交互管理。支持 **VLESS / VMess / Trojan / Shadowsocks / SOCKS5 / HTTP** 六种协议，**每条代理创建时自动验证连通性**。

---

## 架构

```
Telegram User ──► Telegram Bot ──► AI Intent Parser (Ollama)
                                      │
                                      ▼
                              ┌──────────────────┐
                              │   Orchestrator    │
                              │  ┌──────┐┌─────┐┌────────┐
                              │  │IPv6  ││Xray ││Firewall│
                              │  │Mgr   ││Mgr  ││Mgr     │
                              │  └──────┘└─────┘└────────┘
                              └────────┬─────────┘
                                       │
                              ┌────────▼─────────┐
                              │   Xray-core       │
                              │  N inbounds =     │
                              │  N IPv6 addresses │
                              │  on /64 subnet    │
                              └──────────────────┘
```

## 功能特性

| 模块 | 功能 |
|------|------|
| **IPv6 地址管理** | 自动检测 `/64` 子网，批量绑定/解绑 IPv6，已释放地址可复用 |
| **多协议代理** | VLESS / VMess / Trojan / Shadowsocks / SOCKS5 / HTTP，基于 Xray-core |
| **连通性验证** | 每条代理创建后**自动 TCP 验证**，最多重试 3 次，不通过的自动回滚 |
| **TLS 加密** | 自签证书 / Let's Encrypt，Trojan 可选手动开启 TLS |
| **AI 智能** | Ollama + qwen2:0.5b，自然语言理解用户意图 + 正则回退 |
| **Telegram Bot** | Inline Keyboard 菜单、分页列表、详情/分享链接/删除确认 |
| **健康检查** | 定时健康检查 + error 代理冷却期（不反复刷屏）+ 自动重启 |
| **安全加固** | 用户白名单、防火墙自动管理、凭证自动生成 |

---

## 系统要求

| 项目 | 最低 | 推荐 |
|------|------|------|
| 操作系统 | Ubuntu 20.04+ | Ubuntu 22.04 |
| Python | 3.10+ | 3.10+ |
| 内存 | 1 GB | 2 GB+ |
| 磁盘 | 5 GB | 10 GB+ |
| IPv6 | /64 子网 | /64 或更大 |
| Xray-core | 1.8.x | 1.8.23 |
| Ollama | 最新 | 最新 |

---

## 快速开始（裸机安装）

### 1. 克隆仓库

```bash
git clone https://github.com/ffei2963-ai/ipv666.git
cd ipv666
```

### 2. 安装依赖

```bash
# Python 依赖
pip install aiohttp pyyaml python-dotenv aiosqlite psutil cryptography Jinja2 python-telegram-bot

# 安装 Xray-core
bash -c "$(curl -L https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ install --version 1.8.23

# 安装 Ollama
curl -fsSL https://ollama.com/install.sh | sh

# 拉取 AI 模型
ollama pull qwen2:0.5b

# 生成 TLS 自签证书
mkdir -p /app/certs
openssl req -x509 -newkey rsa:2048 -keyout /app/certs/key.pem \
  -out /app/certs/cert.pem -days 3650 -nodes -subj "/CN=localhost"

# 创建所需目录
mkdir -p /var/log/xray /var/log/app /usr/local/etc/xray
```

### 3. 配置 `.env`

```bash
cp .env.example .env
```

```env
TELEGRAM_BOT_TOKEN=你的Bot Token          # 从 @BotFather 获取
TELEGRAM_ADMIN_IDS=你的Telegram用户ID     # 从 @userinfobot 获取
OLLAMA_MODEL=qwen2:0.5b
PROXY_BASE_PORT=10000
HEALTH_CHECK_INTERVAL=60
VPS_IPV6_INTERFACE=eth0
TLS_ENABLED=false
```

### 4. 启动

```bash
# 启动 Xray-core（空配置）
/usr/local/bin/xray run -config /usr/local/etc/xray/config.json > /dev/null 2>&1 &

# 启动 IPv666
export CONFIG_PATH=$(pwd)/config/settings.yaml \
       DB_DIR=$(pwd)/data \
       LOG_DIR=/var/log/app \
       PYTHONPATH=$(pwd)
python3 src/main.py
```

### 5. Docker 部署（备选）

```bash
cp .env.example .env    # 编辑 .env 填好 Token
docker compose up -d --build
docker compose logs -f
```

---

## Bot 使用指南

搜索 `@ipv666bot`（或你设置的 Bot 名称），发送 `/start` 即可看到控制面板。

### Inline Keyboard 菜单

```
🤖 IPv666 ── 控制面板
┌──────────────────────┐
│     📦 创建代理       │
├──────────────────────┤
│ 📋 代理列表 │ 📊 统计 │
├──────────────────────┤
│ 🔍 健康检查 │ ℹ️ 帮助 │
└──────────────────────┘
```

### 创建代理

| 方式 | 示例 |
|------|------|
| 快捷预设 | 点击菜单中的 "1x VLESS+SS" / "3x 全部协议" 等 |
| 命令行 | `/create 5 vless ss socks5` |
| 自然语言 | `创建 10 个 vmess 代理` / `create 3 proxies with vless` |

### 代理列表

- 分页浏览（每页 5 条）
- 每条显示状态图标（🟢 active / 🔴 error）
- 点击代理查看详情、分享链接、删除确认

### 命令行参考

| 命令 | 示例 |
|------|------|
| `/start` 或 `/menu` | 打开控制面板 |
| `/create 5 vless ss` | 创建 5 个代理 |
| `/list` | 浏览所有代理 |
| `/delete 3` | 删除代理 #3 |
| `/stats` | 查看统计 |
| `/help` | 帮助 |

---

## 协议详情

| 协议 | 用户输入 | 验证方式 | 认证方式 | 加密 | TLS |
|------|----------|----------|----------|------|-----|
| **VLESS** | vless | TCP Connect | UUID | none | 可选 |
| **VMess** | vmess | TCP Connect | UUID + alterId=0 | auto | 可选 |
| **Trojan** | trojan | TCP Connect | 密码 (24字符) | — | 可选 |
| **Shadowsocks** | ss / shadowsocks | TCP Connect | aes-256-gcm + 密码 | aes-256-gcm | — |
| **SOCKS5** | socks5 / socks | TCP Connect | user:proxy + 密码 | — | — |
| **HTTP** | http / https | TCP Connect | user:proxy + 密码 | — | — |

> **注意**: 本项目使用 TCP Connect 验证代理可达性（不进行协议握手）。要真正使用代理，需用对应协议的客户端（v2rayN、Clash 等）。

---

## 代理凭证

每条代理自动生成唯一凭证，在 Bot 详情页可查看：

```
🔐 账号密码：
🔹 VLESS：UUID: 550e8400-e29b-41d4-a716-446655440000
🔸 VMess：UUID: 6ba7b810-9dad-11d1-80b4-00c04fd430c8
🔺 Trojan：密码: Kx9#mP2$vL7qW8!aB3cD
🟣 Shadowsocks：方法: aes-256-gcm  密码: a1b2c3d4...（32位hex）
🟠 SOCKS5：用户: proxy  密码: Xy8#qR3
🟤 HTTP：用户: proxy  密码: Jk5!mL9
```

---

## 端口分配

```
代理 #1: IPv6 2602:294:1:a18::2,  base_port=10000
  ├── VLESS       :10000
  ├── VMess       :10001
  └── SOCKS5      :10002

代理 #2: IPv6 2602:294:1:a18::3,  base_port=10003
  ├── VLESS       :10003
  └── SOCKS5      :10004
```

---

## 配置参考

### settings.yaml

```yaml
agent:
  health_check_interval: 60       # 健康检查间隔（秒）
  max_consecutive_failures: 3     # 连续失败 N 次触发自动修复
  verify_new_proxy: true          # 创建时验证连通性（强烈推荐 true）
  max_proxies: 5000               # 代理数量上限

proxy:
  base_port: 10000                # 起始端口

ipv6:
  interface: eth0                 # IPv6 网卡
  address_start_offset: 2         # 起始 IPv6 offset（::2 开始）
```

### 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `TELEGRAM_BOT_TOKEN` | Bot Token | 必填 |
| `TELEGRAM_ADMIN_IDS` | 管理员 ID（逗号分隔） | 必填 |
| `OLLAMA_MODEL` | AI 模型 | qwen2:0.5b |
| `PROXY_BASE_PORT` | 起始端口 | 10000 |
| `HEALTH_CHECK_INTERVAL` | 健康检查间隔 | 60 |
| `VPS_IPV6_INTERFACE` | IPv6 网卡 | eth0 |

---

## 目录结构

```
ipv666/
├── README.md
├── Dockerfile
├── docker-compose.yml
├── .env.example / .env
├── requirements.txt
├── entrypoint.sh
├── config/
│   └── settings.yaml          # 全局 YAML 配置
├── scripts/                   # Shell 安装脚本（Docker 用）
├── src/
│   ├── main.py                # 应用入口
│   ├── bot/
│   │   └── telegram_bot.py    # Bot + Inline Keyboard（中文）
│   ├── agent/
│   │   ├── orchestrator.py    # 核心编排：批量创建/删除/验证
│   │   ├── intent_parser.py   # AI + 正则 意图解析
│   │   └── health_checker.py  # 定时健康检查 + 冷却
│   ├── ipv6/
│   │   ├── address_manager.py # IPv6 分配/释放/复用
│   │   └── subnet_detector.py # 子网检测
│   ├── proxy/
│   │   ├── xray_manager.py    # Xray 进程管理（kill+restart）
│   │   ├── xray_templates.py  # 6 协议 inbound 模板
│   │   ├── share_link.py      # 分享链接生成
│   │   ├── verifier.py        # TCP 连通性验证
│   │   └── tls_manager.py     # TLS 证书管理
│   ├── llm/
│   │   └── ollama_client.py   # Ollama API 封装
│   ├── security/
│   │   ├── firewall.py        # iptables/nftables 管理
│   │   └── auth.py            # 用户白名单
│   ├── db/
│   │   ├── database.py        # SQLite
│   │   └── models.py          # 数据模型
│   └── utils/
│       ├── config.py          # 配置加载
│       ├── credential.py      # UUID/密码生成
│       ├── logger.py          # 日志
│       └── rollback.py        # 事务回滚
├── data/                      # SQLite + 测试结果
├── certs/                     # TLS 证书
└── test_simulation.py         # 30 天模拟测试
```

---

## 故障排查

### 代理创建后全部失败

```bash
# 检查 Xray 是否运行
pgrep xray && echo "Xray OK" || echo "Xray NOT running"

# 启动 Xray
/usr/local/bin/xray run -config /usr/local/etc/xray/config.json > /dev/null 2>&1 &

# 检查证书是否存在
ls -la /app/certs/cert.pem /app/certs/key.pem

# 验证 Xray 配置
/usr/local/bin/xray run -config /usr/local/etc/xray/config.json -test
```

### Xray 启动失败

常见原因：Trojan 协议需要 TLS 证书。运行：
```bash
mkdir -p /app/certs
openssl req -x509 -newkey rsa:2048 -keyout /app/certs/key.pem \
  -out /app/certs/cert.pem -days 3650 -nodes -subj "/CN=localhost"
```

### 数据库锁死

```bash
# 停止所有 Python 进程，删除 DB 重建
pkill -f "src/main.py"
rm -f /root/ipv666/data/ipv666.db*
# 重新启动即可自动建库
```

### Bot 无响应

```bash
# 检查 Bot 日志
grep -E "error|Telegram|Bot|IPv666" /var/log/app/ipv666.log | tail -20

# 验证 Token
curl "https://api.telegram.org/bot<你的TOKEN>/getMe"

# 确认用户 ID 已添加到白名单
grep "Added bot user" /var/log/app/ipv666.log
```

### IPv6 地址无法绑定

```bash
# 查看当前已绑定 IPv6
ip -6 addr show dev eth0 | grep global

# 检查子网前缀
ip -6 route show dev eth0

# 手动测试绑定
ip -6 addr add YOUR_SUBNET::ffff/64 dev eth0
```

---

## 运行测试

```bash
# 30 天模拟 + Bug 检测
export CONFIG_PATH=$(pwd)/config/settings.yaml \
       DB_DIR=$(pwd)/data \
       PYTHONPATH=$(pwd)
python3 test_simulation.py

# 60 天真实验证（需要 Xray 和 Ollama 运行中）
python3 /tmp/opencode/ipv666-test/60day_simulation.py
```

---

## 安全建议

1. **修改默认端口**: `PROXY_BASE_PORT=20000` 避免端口扫描
2. **启用白名单**: `TELEGRAM_ADMIN_IDS` 中仅填写自己的 ID
3. **不要泄露 `.env`**: 已加入 `.gitignore`
4. **TLS 加密**: 生产环境设置 `TLS_ENABLED=true` + `TLS_DOMAIN`
5. **定期更新**: `pip install --upgrade` 依赖 + 更新 Xray-core

---

## 开发记录 (Git Log)

| 提交 | 内容 |
|------|------|
| `b5919ae` | 修复: Trojan TLS 可选, Shadowsocks/HTTP 补充 streamSettings |
| `59dbb31` | 修复: SIGHUP→kill+restart, 失败代理物理 DELETE, 并行验证 |
| `eb21d3b` | 修复: 批量回滚延迟 Xray 重载 |
| `7e7007e` | 修复: IPv6 地址复用 |
| `b462ce9` | 修复: 批量创建代理 |
| `ea39b7e` | 修复: 验证重试 3 次 |
| `3513918` | 功能: Bot 中文 Inline Keyboard UI |

---

## 技术栈

- **代理引擎**: [Xray-core](https://github.com/XTLS/Xray-core) v1.8.23
- **AI**: [Ollama](https://ollama.com/) + qwen2:0.5b
- **Bot**: [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) v21.x
- **数据库**: SQLite (aiosqlite)
- **并发**: asyncio
- **TLS**: openssl / Let's Encrypt

## License

MIT

## 免责声明

本项目仅供学习和研究使用。请遵守当地法律法规，合理使用代理服务。
