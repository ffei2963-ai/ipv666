# IPv666 - IPv6 站群代理服务器

[![Docker](https://img.shields.io/badge/Docker-required-blue)](https://www.docker.com/)
[![Python](https://img.shields.io/badge/Python-3.10+-green)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

基于 Docker 的多协议 IPv6 代理管理平台。将一台仅有一个 IPv6 地址的 VPS 变成可动态创建/管理数万个 IPv6 代理的站群服务器。集成 Ollama AI（qwen2:0.5b）实现通过 Telegram Bot 的自然语言交互式管理。

## 架构

```
                    ┌─────────────────────────────────┐
  Telegram User ───►│    Telegram Bot                 │
                    │    (python-telegram-bot)         │
                    └──────────┬──────────────────────┘
                               │
                               ▼
                    ┌─────────────────────────────────┐
                    │    AI Intent Parser             │
                    │    (Ollama + qwen2:0.5b)        │
                    └──────────┬──────────────────────┘
                               │
                               ▼
          ┌─────────────────────────────────────────────┐
          │            Orchestrator                      │
          │  ┌───────────┐ ┌──────────┐ ┌───────────┐  │
          │  │ IPv6 Mgr  │ │Xray Mgr  │ │Firewall   │  │
          │  └───────────┘ └──────────┘ └───────────┘  │
          └──────────────────┬──────────────────────────┘
                             │
                             ▼
          ┌─────────────────────────────────────────────┐
          │            Docker Container                  │
          │  (host network + privileged)                 │
          │                                             │
          │  ip addr add ::2/64 ... ::N/64              │
          │  Xray-core: N inbounds on N IPv6            │
          └─────────────────────────────────────────────┘
```

## 功能特性

- **IPv6 地址管理**: 自动检测 `/64`（或更大）子网、批量绑定/解绑 IPv6 地址、重启后自动恢复、NDP Proxy 适配
- **多协议代理**: VLESS / VMess / Trojan / Shadowsocks / SOCKS5 / HTTP，基于 Xray-core 六合一引擎
- **TLS 加密**: Let's Encrypt 自动申请/续期，或自签证书降级
- **AI 智能**: Ollama 运行 qwen2:0.5b，自然语言理解用户意图
- **Telegram Bot**: 自然语言对话式管理、用户白名单、分享链接自动生成
- **运维自动化**: 健康检查 + 自动重启故障代理、事务回滚、日志轮转、防火墙自动管理
- **安全加固**: 最小权限、非 root 服务、TLS 全链路、用户鉴权

## 系统要求

| 项目 | 最低要求 | 推荐 |
|------|---------|------|
| 操作系统 | Linux (Ubuntu 20.04+) | Ubuntu 22.04 |
| 内存 | 1 GB | 2 GB+ |
| 磁盘 | 5 GB | 10 GB+ |
| IPv6 | /64 子网 | /64 或 /48 |
| Docker | 20.10+ | 最新版 |
| Docker Compose | 1.29+ | v2.x |

## 快速开始

### 1. 克隆仓库

```bash
git clone https://github.com/ffei2963-ai/ipv666.git
cd ipv666
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`：

```env
TELEGRAM_BOT_TOKEN=your_bot_token_here      # 从 @BotFather 获取
TELEGRAM_ADMIN_IDS=123456789                # 你的 Telegram 用户 ID
OLLAMA_MODEL=qwen2:0.5b                     # AI 模型
PROXY_BASE_PORT=10000                       # 代理起始端口
HEALTH_CHECK_INTERVAL=60                    # 健康检查间隔(秒)
TLS_ENABLED=false                           # 是否启用 TLS
TLS_DOMAIN=                                 # TLS 域名(需要公网 DNS)
TLS_EMAIL=admin@example.com                 # Let's Encrypt 邮箱
VPS_IPV6_INTERFACE=eth0                     # IPv6 所在网卡
```

### 3. 获取 Telegram Bot Token

1. 在 Telegram 搜索 `@BotFather`
2. 发送 `/newbot` 创建机器人
3. 获取 Bot Token
4. 获取你的用户 ID: 搜索 `@userinfobot` 发送任意消息

### 4. 构建并启动

```bash
docker compose up -d --build
```

首次启动会：
- 检测 VPS IPv6 子网
- 配置 NDP Proxy（如需要）
- 配置防火墙规则
- 下载并启动 Ollama + qwen2:0.5b 模型（约 400MB）
- 启动 Xray-core
- 启动 Telegram Bot

查看日志：

```bash
docker compose logs -f
```

### 5. 使用 Bot

在 Telegram 中向你的 Bot 发送消息：

```
创建5个代理，只要 VLESS 和 Shadowsocks

查一下现在有多少代理

删除代理 #3

检查代理是否正常
```

## 命令参考

| 命令 | 说明 | 示例 |
|------|------|------|
| `/create <count> [protocols]` | 创建代理 | `/create 5 vless ss` |
| `/list` | 列出所有代理 | `/list` |
| `/delete <id>` | 删除代理 | `/delete 3` |
| `/stats` | 查看统计 | `/stats` |
| `/help` | 查看帮助 | `/help` |

## 代理协议映射

| 用户输入 | 映射协议 |
|---------|---------|
| vless | VLESS |
| vmess | VMess |
| trojan | Trojan |
| ss / shadowsocks | Shadowsocks |
| socks5 / socks | SOCKS5 |
| http / https | HTTP |

## 端口分配

每个代理根据所选协议数量占用对应端口：

```
代理 #1: IPv6 ::2, base_port=10000
  ├── VLESS       :10000
  ├── Shadowsocks :10001
  └── SOCKS5      :10002

代理 #2: IPv6 ::3, base_port=10003
  ├── VLESS       :10003
  └── SOCKS5      :10004
```

## 目录结构

```
ipv666/
├── Dockerfile                    # 容器构建文件
├── docker-compose.yml            # 一键部署配置
├── .env.example                  # 环境变量模板
├── requirements.txt              # Python 依赖
├── entrypoint.sh                 # 容器启动脚本
├── healthcheck.sh                # Docker 健康检查
├── config/
│   └── settings.yaml             # 全局配置
├── scripts/
│   ├── setup_ipv6.sh             # IPv6 子网检测与配置
│   ├── setup_ndp.sh              # NDP Proxy 检测与配置
│   ├── setup_ollama.sh           # Ollama 安装与模型拉取
│   ├── setup_xray.sh             # Xray-core 初始化
│   ├── setup_tls.sh              # TLS 证书管理
│   └── setup_firewall.sh         # 防火墙规则配置
├── src/
│   ├── main.py                   # 应用入口
│   ├── bot/
│   │   └── telegram_bot.py       # Telegram Bot 处理
│   ├── agent/
│   │   ├── orchestrator.py       # 核心编排器
│   │   ├── intent_parser.py      # AI 意图解析
│   │   └── health_checker.py     # 定时健康检查
│   ├── ipv6/
│   │   ├── address_manager.py    # IPv6 地址管理
│   │   ├── subnet_detector.py    # 子网自动检测
│   │   └── ndp_manager.py        # NDP Proxy 管理
│   ├── proxy/
│   │   ├── xray_manager.py       # Xray 配置与进程管理
│   │   ├── xray_templates.py     # 六协议 inbound 模板
│   │   ├── tls_manager.py        # TLS 证书管理
│   │   ├── share_link.py         # 分享链接生成
│   │   └── verifier.py           # 代理连通性验证
│   ├── llm/
│   │   └── ollama_client.py      # Ollama API 封装
│   ├── security/
│   │   ├── firewall.py           # 防火墙自动管理
│   │   └── auth.py               # 用户鉴权
│   ├── db/
│   │   ├── database.py           # SQLite 数据库操作
│   │   └── models.py             # 数据模型
│   └── utils/
│       ├── config.py             # 配置加载
│       ├── credential.py         # 凭证生成
│       ├── logger.py             # 日志管理
│       └── rollback.py           # 事务回滚
├── data/                         # SQLite 数据(持久化)
├── ollama_data/                  # Ollama 模型(持久化)
├── xray_configs/                 # Xray 配置(持久化)
└── certs/                        # TLS 证书(持久化)
```

## 代理存活保证

- **定时健康检查**: 每 60 秒检查所有代理连通性
- **自动恢复**: 连续失败 3 次的代理自动重启 Xray
- **持久化恢复**: 容器重启后自动恢复所有已分配的 IPv6 地址

## 安全建议

1. **修改默认端口**: 在 `.env` 中设置 `PROXY_BASE_PORT=20000` 或其他非标准端口
2. **启用用户白名单**: 在 `.env` 的 `TELEGRAM_ADMIN_IDS` 中仅添加自己的 ID
3. **定期更新**: `docker compose pull && docker compose up -d`
4. **防火墙加固**: 系统自动管理 iptables/ip6tables 规则
5. **TLS 加密**: 设置 `TLS_ENABLED=true` 并配置 `TLS_DOMAIN`

## 故障排查

### Ollama 模型下载失败

```bash
docker compose exec ipv666 ollama pull qwen2:0.5b
```

### IPv6 地址无法绑定

```bash
# 检查 VPS IPv6 子网
docker compose exec ipv666 ip -6 addr show

# 手动测试绑定
docker compose exec ipv666 ip -6 addr add YOUR_SUBNET::ffff/64 dev eth0
```

### Telegram Bot 无响应

```bash
# 查看日志
docker compose logs -f ipv666 | grep -i telegram

# 检查 Bot Token
docker compose exec ipv666 env | grep TELEGRAM
```

### 代理无法连接

```bash
# 检查 Xray 状态
docker compose exec ipv666 pgrep -a xray

# 检查防火墙规则
docker compose exec ipv666 ip6tables -L -n | grep 10000
```

## 技术栈

- **容器**: Docker + Docker Compose
- **代理引擎**: [Xray-core](https://github.com/XTLS/Xray-core) v1.8.x
- **AI 模型**: [Ollama](https://ollama.com/) + qwen2:0.5b
- **Bot 框架**: [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) v21.x
- **数据库**: SQLite (aiosqlite)
- **TLS**: [acme.sh](https://github.com/acmesh-official/acme.sh) + Let's Encrypt
- **NDP Proxy**: ndppd
- **防火墙**: iptables / nftables

## License

MIT

## 免责声明

本项目仅供学习和研究使用。请遵守当地法律法规，合理使用代理服务。
