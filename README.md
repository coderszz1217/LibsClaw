# LibsClaw

LibsClaw 是一个多平台 LLM 聊天机器人及 Agent 开发框架，支持接入多种即时通讯平台与主流模型服务，内置 WebUI、插件系统、知识库、Agent 沙箱等能力。

> 本项目基于 AGPL-3.0 协议的开源软件构建，遵循 AGPL-3.0-or-later 许可发布，详见 [LICENSE](LICENSE)。

## 快速开始

### 源码运行

需要 Python 3.12+、[uv](https://docs.astral.sh/uv/)、Node.js 与 pnpm。

```bash
# 后端
uv sync
uv run main.py

# 前端（构建 WebUI）
cd dashboard
pnpm install
pnpm build
# 将 dashboard/dist 复制到 data/dist
```

启动后访问 `http://localhost:6185`，初始用户名为 `LibsClaw`，初始密码在首次启动日志中输出。

### Docker

```bash
docker build -t libsclaw:latest .
docker compose up -d
```

## 开发

```bash
pip install pre-commit
pre-commit install
```

- 后端测试：`uv run pytest tests`
- 前端测试：`cd dashboard && node --test tests/*.mjs`
- 代码规范：`ruff check` / `ruff format`

## 许可

本项目遵循 [AGPL-3.0-or-later](LICENSE) 协议。若基于本项目对外提供网络服务，请依照协议开放对应源代码。
