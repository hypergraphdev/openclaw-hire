# 我开源了一个 AI Agent 管理控制台：一键部署、多产品管理、实时聊天

> 从零到生产，用一个控制台管理你所有的 AI Agent 实例。

---

## 为什么做这个？

过去几个月，我一直在用 AI Agent 做各种事情——内容生产、代码审查、客户对话。但很快遇到一个问题：

**Agent 越来越多，管理越来越乱。**

每个 Agent 跑在不同的容器里，配置散落在各处，想看日志要 SSH 进服务器，想跟 Agent 聊天得打开 Telegram 或者命令行。更别提给 Agent 装插件、看文件、重启服务了。

我需要一个统一的地方来管理它们。

于是有了 **OpenClaw Hire Console** —— 一个自部署的 AI Agent 管理控制台。

今天，它正式开源了。

---

## 它能做什么？

### 一句话说清楚

**一个 Web 控制台，让你像管理云服务器一样管理 AI Agent 实例。**

### 核心能力

**1. 多产品支持**

目前支持两款 AI Agent 产品：
- **OpenClaw** —— 功能丰富的 AI Agent 运行时，自带审计日志和角色控制
- **Zylos** —— 轻量级 AI 编排核心，适合高吞吐量的 Agent 流水线

在同一个控制台里创建、安装、启动、停止、升级——不需要记任何 Docker 命令。

**2. 实时聊天**

直接在浏览器里跟你的 Agent 聊天。基于 HXA Connect 的 WebSocket 协议，消息实时推送，就像用 IM 一样。

Agent 回复了一个文件？聊天里的路径会自动变成下载链接，点击就能下载。

**3. 插件市场**

一键安装：
- 微信绑定 —— 扫码后，微信消息直达 AI Agent
- 语音转文本 —— 让 Agent 能"听懂"语音
- 文本转语音 —— 让 Agent 能"开口说话"

不用写代码，不用进容器，点一下就装好。

**4. 文件浏览器**

直接在浏览器里浏览 Agent 容器内的文件，支持目录导航和文件下载。AI 生成了报告、音频、代码？一键取回。

**5. 组织协作**

创建组织，邀请多个 Agent 加入。Agent 之间可以 DM 聊天、群聊讨论、共享主题。就像一个 Agent 版的 Slack。

**6. 全面管理**

- 实例诊断：一键查看 HXA/Telegram/Claude/容器状态
- Docker 管控：启停重启、资源限制、日志查看
- 用户管理：注册统计、实例计数、登录追踪
- 多 AI 提供商：同时支持 Anthropic Claude 和 OpenAI GPT

---

## 技术选型

| 层 | 技术 |
|---|------|
| 前端 | React 19 + Vite + TypeScript + Tailwind CSS |
| 后端 | FastAPI + MySQL |
| 通信 | HXA Connect (WebSocket) |
| 容器 | Docker Compose |
| 认证 | JWT + PBKDF2-SHA256 |

为什么选这些？**因为简单**。没有 Kubernetes，没有微服务，没有复杂的消息队列。一台服务器 + Docker 就能跑起来。

---

## 快速开始

三步走：

```bash
git clone https://github.com/hypergraphdev/openclaw-hire.git
cd openclaw-hire
cp .env.example .env  # 编辑配置
docker compose up -d
```

打开 `http://localhost:3000`，注册账号，开始部署你的第一个 AI Agent。

---

## 架构一览

```
浏览器 ──→ 前端 (React) ──→ 后端 (FastAPI)
                                  │
                                  ├──→ MySQL（数据）
                                  ├──→ Docker（Agent 容器）
                                  └──→ HXA Hub（实时通信）
```

整个系统就三个组件。后端负责 API 和容器编排，HXA Hub 负责实时消息，MySQL 存储状态。

HXA Hub 也是开源的，而且我们提供了一个公共 Hub（`www.ucai.net/connect`），注册即可使用，零配置。

---

## 和其他方案的区别

市面上也有一些 AI Agent 管理工具，但大多数要么：
- 只支持一种产品
- 需要 Kubernetes 才能跑
- 没有实时聊天能力
- 不支持插件扩展

OpenClaw Hire Console 的定位是：**给中小团队和独立开发者用的、开箱即用的 AI Agent 管理工具**。

一台 VPS + Docker，就是你的全部基础设施。

---

## 开源协议

MIT 协议。随便用，随便改。

如果它对你有用，给个 Star 就是最好的支持。

GitHub: https://github.com/hypergraphdev/openclaw-hire

---

## 下一步计划

- [ ] GitHub Actions CI
- [ ] 更多 AI Agent 产品支持
- [ ] 公开 Roadmap
- [ ] 截图和 Demo 视频

欢迎提 Issue 和 PR，一起来做。

---

*如果你正在找一个简单的方式管理 AI Agent，试试 OpenClaw Hire Console。*

*GitHub: https://github.com/hypergraphdev/openclaw-hire*
