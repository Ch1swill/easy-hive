# Easy-Hive Bot

Telegram Bot，对接 [影巢 (HDHive)](https://hdhive.com) Open API，提供片名搜索、资源查询、一键转存到 115 网盘等功能。

## 功能

- **片名搜索** — 发送片名自动查询 TMDB，返回带海报的卡片（需配置 TMDB API Key）
- **影巢资源查询** — 按 TMDB ID 查询影巢资源，展示分辨率、片源、字幕、体积、链接状态等信息
- **一键转存到 115** — 通过 [Symedia](https://www.symedia.top/) cloud\_helper 插件，解锁影巢资源后自动转存到 115 网盘指定文件夹
- **网盘类型过滤** — 可按 pan\_type（115、123、quark、baidu、ed2k）过滤资源
- **白名单** — 仅允许指定 chat\_id 使用 Bot

## 快速开始

### 1. 准备配置

```bash
cp .env.example .env
```

编辑 `.env`，至少填写：

| 变量 | 说明 |
|------|------|
| `HDHIVE_API_KEY` | 影巢 API Key（[获取](https://hdhive.com) → 个人设置 → API Keys） |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot Token（从 [@BotFather](https://t.me/BotFather) 获取） |
| `TELEGRAM_CHAT_ID` | 允许使用 Bot 的 chat ID，逗号分隔 |

可选配置见 [.env.example](.env.example) 中的详细注释。

### 2a. Docker 部署（推荐）

```bash
docker compose up -d --build
```

### 2b. 本地运行

```bash
pip install -r requirements.txt
python -m bot.main
```

## 命令

| 命令 | 说明 |
|------|------|
| `/start` | 显示欢迎信息 |
| `/help` | 查看配置状态与使用说明 |
| `/movie <TMDB_ID>` | 按电影 TMDB ID 查询影巢资源 |
| `/tv <TMDB_ID>` | 按剧集 TMDB ID 查询影巢资源 |
| 发送任意片名 | TMDB 搜索（需配置 `TMDB_API_KEY`） |

## 项目结构

```
easy-hive/
├── bot/
│   ├── main.py          # 入口，日志配置，Bot 启动
│   ├── config.py         # 环境变量解析
│   ├── handlers.py       # Telegram 命令与回调处理
│   ├── tmdb.py           # TMDB API 搜索与详情
│   ├── hdhive.py         # 影巢 Open API 资源查询与解锁
│   ├── symedia.py        # Symedia 转存接口
│   └── formatting.py     # 资源卡片文本格式化
├── .env.example          # 配置模板（含详细注释）
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── README.md
```

## 日志

- 终端输出 + 文件 `logs/bot.log`
- 日志按天轮转，保留最近 2 天
- 带 emoji 级别前缀：ℹ️ INFO / ⚠️ WARNING / ❌ ERROR

## 技术栈

- Python 3.12+
- [aiogram 3](https://docs.aiogram.dev/) — Telegram Bot 框架
- [httpx](https://www.python-httpx.org/) — 异步 HTTP 客户端
- [python-dotenv](https://github.com/theskumar/python-dotenv) — 环境变量管理

## 许可证

[MIT License](LICENSE)
