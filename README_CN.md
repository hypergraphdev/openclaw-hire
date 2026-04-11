# OpenClaw Hire 控制台

[English](README.md) | 中文文档

自托管的 Web 控制台，用于部署和管理 AI Agent 实例。支持 [OpenClaw](https://github.com/openclaw/openclaw)、[Zylos](https://github.com/zylos-ai/zylos-core) 和 [Hermes Agent](https://github.com/NousResearch/hermes-agent) 三种产品，提供实时聊天、组织管理和插件市场功能。

## 功能特性

### 实例管理
- **三种产品** — OpenClaw（Claude 驱动）、Zylos（轻量编排）、Hermes Agent（自主学习，200+ 模型）
- **完整生命周期** — 通过 Docker Compose 创建、安装、启动、停止、重启、升级、卸载 AI Agent 实例
- **自检修复** — 自动诊断（容器状态、DB 元数据、API Key、HXA 配置、WebSocket、npm 依赖、AI 运行时），一键修复
- **文件浏览** — 在 Web 界面中浏览容器文件系统，直接下载文件
- **Docker 控制** — 查看容器日志、设置 CPU/内存限制、在管理面板中管理容器生命周期
- **镜像自动拉取** — compose up 前自动拉取最新镜像，避免旧缓存

### 通信渠道
- **实时聊天** — 通过 HXA Connect（WebSocket）与 AI Agent 对话，支持消息复制
- **Thread 质量控制** — 结构化任务协议用于 Bots Team，AI 驱动的质量评估门，验收标准和自动修改请求
- **微信集成** — 扫码登录连接微信（OpenClaw/Zylos），Hermes 版通过 HTTP Bridge
- **Telegram 集成** — 绑定 Telegram Bot。Hermes 使用内置 Gateway，Zylos/OpenClaw 使用 HXA 插件
- **HXA 组织** — 多组织 Bot 通信枢纽，支持 Thread 群聊、私信和消息搜索

### 插件市场
- **一键安装** — 直接安装插件到运行中的容器
- **可用插件** — 微信（zylos-weixin / hermes-weixin）、Whisper 语音识别、Edge-TTS 语音合成

### 用户设置
- **用户级 API Key** — 每个用户可配置自己的 API Key（Anthropic/OpenAI/OpenRouter/DeepSeek），优先于管理员全局配置
- **按产品区分配置** — Hermes 显示 OpenRouter 字段，OpenClaw/Zylos 显示 Anthropic 字段

### 管理后台
- **全局设置** — 配置默认 AI 模型、API Key（Anthropic/OpenAI）、HXA Hub 连接
- **用户管理** — 第一个注册的用户自动成为管理员
- **HXA 组织管理** — 创建/删除组织、管理 Agent、轮换密钥、在组织间转移 Bot
- **实例诊断** — 逐实例健康检查，包括 HXA/Telegram/Claude/容器状态
- **中英双语** — 完整的中英文界面支持

## 支持的产品

| 产品 | 运行时 | 主要特性 |
|------|--------|---------|
| **OpenClaw** | Claude Code | 角色访问控制、审计日志、Docker 原生 |
| **Zylos** | Claude Code / Codex | 插件架构、任务调度、轻量 |
| **Hermes Agent** | 多模型 (200+) | 自主学习技能、持久记忆、多平台消息 |

## 快速开始（Docker）

```bash
git clone https://github.com/hypergraphdev/openclaw-hire.git
cd openclaw-hire
cp .env.example .env

# 编辑 .env，至少设置以下两项：
#   SECRET_KEY=你的随机密钥
#   OPENCLAW_HOME=/openclaw-hire的完整路径  （必须是宿主机路径，不是容器路径）

docker compose up -d
```

> **国内用户：** 如果 Docker Hub 被墙，先配置镜像源：
> ```bash
> sudo mkdir -p /etc/docker
> echo '{"registry-mirrors":["https://docker.1ms.run"]}' | sudo tee /etc/docker/daemon.json
> sudo systemctl restart docker
> ```

访问 `http://localhost:3000`，注册账号即可开始部署 AI Agent。第一个注册的用户自动成为管理员。

## 手动安装

### 前置条件

- Python 3.10+
- Node.js 20+
- MySQL 8.0
- Docker（用于运行 AI Agent 实例）

### 后端

```bash
cd backend
pip install -r requirements.txt
cp ../.env.example ../.env
# 编辑 ../.env

uvicorn app.main:app --reload --port 8012
```

### 前端

```bash
cd frontend
npm install
npm run dev
```

### 数据库

创建 MySQL 数据库和用户：

```sql
CREATE DATABASE openclaw_hire CHARACTER SET utf8mb4;
CREATE USER 'openclaw'@'localhost' IDENTIFIED BY '你的密码';
GRANT ALL ON openclaw_hire.* TO 'openclaw'@'localhost';
```

数据表会在首次启动时自动创建。

## 配置说明

所有配置可通过环境变量或**管理后台 > 全局设置**面板进行修改。

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `SECRET_KEY` | *（必填）* | JWT 签名密钥 |
| `DB_HOST` | `localhost` | MySQL 主机 |
| `DB_NAME` | `openclaw_hire` | MySQL 数据库名 |
| `DB_USER` | `openclaw` | MySQL 用户名 |
| `DB_PASSWORD` | | MySQL 密码 |
| `SITE_BASE_URL` | `https://www.ucai.net` | 部署的公网 URL |
| `HXA_HUB_URL` | `https://www.ucai.net/connect` | HXA Connect Hub 地址（可使用公共 Hub） |
| `ANTHROPIC_BASE_URL` | | Anthropic API 代理地址 |
| `ANTHROPIC_AUTH_TOKEN` | | Anthropic API Key |
| `OPENCLAW_HOME` | *（项目根目录）* | 运行时数据的基础路径 |
| `VITE_API_BASE` | | 前端 API 地址 |
| `VITE_BASE_PATH` | `/` | 前端基础路径 |

### 管理后台配置

登录后，进入**设置**页面可配置：

- **AI 模型** — 新实例的默认模型（如 `claude-sonnet-4-5`、`claude-opus-4`）
- **API Key** — Anthropic / OpenAI 凭证
- **HXA Hub** — 组织 ID、密钥、邀请码

### 用户级设置

每个用户可在实例详情页配置自己的 API Key：

- **OpenClaw/Zylos** — Anthropic Base URL、Auth Token、OpenAI Key
- **Hermes Agent** — OpenRouter/DeepSeek API Key、Base URL、模型

用户设置在创建/配置实例时优先于管理员全局配置。

完整配置模板参见 [`.env.example`](.env.example)。

## 架构

### 系统架构

```mermaid
graph TB
    subgraph Client["客户端"]
        Browser["浏览器"]
        WeChat["微信"]
        Telegram["Telegram"]
    end

    subgraph Console["OpenClaw Hire 控制台"]
        Frontend["前端<br/>React 19 + Vite 7 + Tailwind"]
        Backend["后端<br/>FastAPI + JWT 认证"]
        MySQL[("MySQL<br/>用户、实例、<br/>配置、设置")]
    end

    subgraph Hub["HXA Connect Hub"]
        HubAPI["REST API + WebSocket"]
        OrgMgmt["组织管理"]
    end

    subgraph Instances["AI Agent 实例 (Docker)"]
        OC["OpenClaw 容器<br/>Gateway + CLI"]
        ZY["Zylos 容器<br/>Claude/Codex 运行时"]
        HM["Hermes 容器<br/>多模型 Gateway"]
        HXAPlugin["HXA Connect 插件"]
        TGPlugin["Telegram 插件"]
        WXPlugin["微信插件"]
        C4["C4 通信桥"]
    end

    Browser -->|HTTPS| Frontend
    Frontend -->|REST API| Backend
    Backend --> MySQL
    Backend -->|Docker API| Instances
    Backend -->|REST + WS| Hub

    Hub <-->|WebSocket| HXAPlugin
    WeChat <-->|长轮询| WXPlugin
    Telegram <-->|Bot API| TGPlugin
    Telegram <-->|Bot API| HM

    WXPlugin -->|C4 接收| C4
    TGPlugin -->|C4 接收| C4
    HXAPlugin -->|C4 接收| C4
    C4 -->|tmux 粘贴| OC
    C4 -->|tmux 粘贴| ZY

    style Console fill:#1a1a2e,stroke:#16213e,color:#fff
    style Hub fill:#0f3460,stroke:#16213e,color:#fff
    style Instances fill:#1a1a2e,stroke:#533483,color:#fff
    style Client fill:#1a1a2e,stroke:#16213e,color:#fff
```

### 实例安装流程

```mermaid
sequenceDiagram
    participant U as 用户
    participant FE as 前端
    participant BE as 后端
    participant D as Docker
    participant Hub as HXA Hub

    U->>FE: 点击"安装"
    FE->>BE: POST /instances/{id}/install
    BE->>BE: 克隆产品仓库
    BE->>BE: 查找/生成 compose 文件
    BE->>BE: 读取用户 API 设置（优先）或全局设置
    BE->>D: docker compose pull + up -d
    D-->>BE: 容器运行中
    BE->>Hub: 在组织中注册 Agent（OpenClaw/Zylos）
    Hub-->>BE: bot_token + agent_id
    BE->>D: 写入配置到容器
    BE-->>FE: 安装完成
    FE-->>U: 状态：运行中
```

**技术栈：**
- **前端：** React 19 + Vite 7 + TypeScript + Tailwind CSS
- **后端：** FastAPI + MySQL (mysql-connector-python)
- **认证：** JWT (HS256, 7 天过期) + PBKDF2-SHA256 密码哈希
- **通信：** HXA Connect Hub (WebSocket)
- **容器：** Docker Compose 管理 AI Agent 实例
- **部署：** Nginx 反向代理，Docker Compose 一键自托管

## HXA Hub

[HXA Connect](https://github.com/hypergraphdev/hxa-connect) 提供实时的 Bot 间通信能力。开源用户可使用**公共 Hub**：`https://www.ucai.net/connect`。

如需自建 Hub，请参考 [hxa-connect 仓库](https://github.com/hypergraphdev/hxa-connect)。

### 首次配置

1. 注册并登录（第一个用户自动成为管理员）
2. 进入**设置**，配置 API Key 和默认模型
3. 进入**管理 > HXA 组织**，创建第一个组织
4. 部署实例 — 会自动加入默认组织

## 参与贡献

请参阅 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 安全策略

请参阅 [SECURITY.md](SECURITY.md)。

## 开源协议

[MIT](LICENSE)
