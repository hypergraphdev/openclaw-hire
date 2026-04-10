# 更新日志

OpenClaw Hire Console 自 v1.0 上线（2026-03-31）以来的所有重要更新。

## [1.3.0] — 2026-04-10 — Hermes Agent 接入 + HXA Python SDK

### 新产品：Hermes Agent
- **第三种产品类型**：接入 [Hermes Agent](https://github.com/NousResearch/hermes-agent)（Nous Research 出品，支持 200+ 模型，自主学习，无厂商锁定）
- 产品目录、安装脚本、容器命名、管理诊断全面适配
- Docker 镜像从源码构建（服务器预构建缓存，后续创建秒级启动）
- Gateway 模式运行，原生支持 Telegram/Discord/Slack/WhatsApp
- API 配置按产品区分：Hermes 显示 OpenRouter/DeepSeek，Zylos/OpenClaw 显示 Anthropic

### Hermes 微信桥接（hermes-weixin）
- 新开源项目：[hypergraphdev/hermes-weixin](https://github.com/hypergraphdev/hermes-weixin)
- 基于 zylos-weixin 移植，C4 通信桥改为 HTTP bridge
- 收到微信消息 → `hermes chat -q` 调用 AI → 回复微信
- 插件市场一键安装：从 GitHub 克隆、编译、启动
- 安装日志弹窗直接显示扫码链接

### Hermes HXA Connect（hermes-hxa-connect）
- 新开源项目：[hypergraphdev/hermes-hxa-connect](https://github.com/hypergraphdev/hermes-hxa-connect)
- Python 版 HXA Connect SDK，实现 bot-to-bot 通信
- REST API 客户端、WebSocket 实时消息、自动重连
- 实例详情页"加入组织"按钮：自动从 GitHub 安装、注册、启动 WS 监听
- 支持 DM 私聊和 Thread 群聊（@提及过滤）

### 用户级 API Key 设置
- 新增 `user_settings` 数据库表，每个用户独立存储 API Key
- `GET/PUT /api/instances/user-settings` 接口
- 实例详情页右侧可折叠"API 配置"卡片
- 用户配置优先于管理员全局配置
- 标签按产品自适应（Hermes → OpenRouter，Zylos → Anthropic）

---

## [1.2.0] — 2026-04-03 — Thread 质量控制 + AUTH_TOKEN 兼容

### Thread 质量控制（Bots Team）
- **结构化任务协议**：Coordinator 发送带验收标准、深度要求、角色分配的结构化任务
- **AI 质量门**：用 Claude 评估 Bot 回复，不达标自动发修改请求
- **任务面板 UI**：Thread 视图可折叠任务列表，创建/评估/跟踪任务
- **@提及**：任务描述中 @ 选人，支持多人任务（项目经理 + 执行者）
- **草稿保存**：任务创建弹窗自动保存到 localStorage，重新打开恢复
- **防误关**：点击外部不关闭弹窗，关闭需确认

### 任务模板增强
- 三步工作流：确认收到 → 执行任务 → 提交成果
- 发送者身份说明（人类主人用 Bot 身份发送）
- 组织内名字说明（@ 后面的名字 = 组织内名字，可能与实例名不同）
- 弹窗加大（任务创建 720px，评估 680px，QC 配置 480px）

### AUTH_TOKEN 代理模式兼容
- 解决三层冲突：entrypoint 认证检查 / zylos init / Claude Code
- 最终方案：宿主 .env 占位符 + workspace .env 空值覆盖
- `_fix_auth_token_mode_compose()` 确保环境变量正确
- `_patch_zylos_api_key_check()` patch entrypoint 接受 AUTH_TOKEN

### 群聊 Anti-Loop
- Thread 阈值放宽 3 倍（60 秒内 18 条触发，冷却 15 分钟）
- DM 保持不变（60 秒内 4 条触发，冷却 5 分钟）

### 可靠性修复
- `_get_agent_token`：同时检查 RUNTIME_ROOT 和 DB runtime_dir，DB org_token 兜底
- `_update_agent_name_in_config`：遍历所有候选路径，不漏改
- 改名后自动重启 hxa-connect 刷新 mention filter
- compose up 前自动 pull 最新镜像
- `_normalize_anthropic_api_key`：防止代理 token 直接写入 zylos init

---

## [1.1.0] — 2026-04-01 — HXA 组织通信 + 实时聊天 + 管理后台

### HXA 组织通信
- 多组织支持，org_secrets 表
- Bot 注册、组织间转移、密钥轮换
- 每用户每组织独立 admin bot 用于 DM 对话
- Hub 一致性检查（DB/容器/Hub 三方同步）

### 实时聊天
- DM 私聊：通过 HXA WebSocket
- Thread 群聊：参与者管理、邀请/踢出、群公告
- 消息复制按钮
- 全文消息搜索（FULLTEXT 索引）

### 管理后台
- 实例诊断：HXA/Telegram/Claude/容器状态
- 实例控制：停止/启动/重启/杀 Claude 进程
- 资源限制：CPU/内存 docker update 即时生效
- 默认 AI 模型配置
- 7 项自检 + 一键修复
- Bot token 校验 + 自动重注册

### 微信集成
- zylos-weixin 插件：扫码登录、长轮询收消息、图片/文件/语音
- 插件市场一键安装
- C4 通信桥接

---

## [1.0.0] — 2026-03-31 — 首版上线

### 核心功能
- SaaS 控制台，部署和管理 OpenClaw / Zylos AI Agent 实例
- Docker Compose 实例生命周期管理
- JWT 认证 + PBKDF2-SHA256 密码哈希
- MySQL 数据库，自动建表
- React 19 + Vite 7 + Tailwind CSS 前端
- FastAPI 后端 + Nginx 反向代理
- 中英文双语界面
