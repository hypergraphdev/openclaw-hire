# 更新日志

OpenClaw Hire Console 自 v1.0 上线（2026-03-31）以来的所有重要更新。

## [1.4.0] — 2026-04-18 — Local Agent（用户自带算力） + 组织聊天全面升级

### 新产品：Local Agent（BYO-Compute）
- **第四种产品类型**：用户本机跑 AI CLI，通过 [@slock-ai/daemon](https://www.npmjs.com/package/@slock-ai/daemon) 接入组织，服务器 0 资源占用
- 部署流程一键化：创建实例 → HXA Connect 同步注册一个 bot → 返回 `npx @slock-ai/daemon@latest --server-url ... --api-key ...` 命令，用户在本机跑即上线
- **CLI 可选**：部署对话框新增 "本机 CLI" 下拉，支持 Claude Code / Codex / Gemini 三种（运行时通过 Slock 协议的 `config.runtime` 下发给 daemon）
- **默认模型**：Claude `sonnet`、Codex `gpt-5.4`、Gemini `gemini-3-flash-preview`（非交互 spawn 必须传具体 id，Pro 免费额度在会话中易耗尽，Flash 更稳）
- 在线状态真实反映 daemon 连接：daemon 连着 → active，断开 → inactive（不依赖 Docker 检查）
- 删除实例同步删除 HXA bot 身份和 `server_settings` 里的 api key
- **配额豁免**：普通用户的 "1 实例" 上限不再计 Local Agent（它不吃服务器资源）
- 新文件：`LocalAgentSetup.tsx`（命令一键复制 + API key 显隐）、`install_service.register_local_agent_bot` / `delete_local_agent_bot`
- 新接口：`GET /api/instances/:id/daemon-command`

### 实例头部编辑
- 状态 pill 旁新增**笔图标**（仅实例主人可见），点开弹出 `InstanceEditModal` 编辑：
  - 实例显示名（新后端端点 `PUT /api/instances/:id/name`）
  - 头像（上传 / 预览 / 移除，2MB 上限 · jpg/png/gif/webp）
- 标题前新增圆形头像徽章（36px，有头像显图、没有显名字首字母）
- **组织内名称（agent_name）刻意不在这里改**——底部提示说明属于"专用入口"（避免误操作影响全组织）
- 头部多展示一行 `组织内: hire_xxx`，优先取 `instance_configs.agent_name`

### 头像功能（跨仓库）
- openclaw-hire：新接口 `GET/POST/DELETE /api/instances/:id/avatar`，代理到 HXA Hub（手搓 multipart 转发）
- 前端 `api.ts`：`getAvatar` / `uploadAvatar` / `deleteAvatar`
- 与 `hxa-connect@1.7.4` 的 `POST /api/me/avatar`、`GET /api/avatars/:filename` 对接
- 上传自动裁剪为 128×128 PNG（hub 侧用 sharp 处理）

### 组织聊天改造
- **侧边栏成员排序**：自己的 bot 永远排最前，其他按字母
- **禁止 DM 他人的 bot**：点击非"我的" bot 会提示"请在群聊 @ 它"，按钮变灰不可点
- **群聊（Thread）改 Slack/Gmail 风**：不用气泡，左侧 36px 方头像 + 顶行 sender 名 + "我的"标签 + 时间 + 下方内容；连续同一 sender 5 分钟内消息折叠 header，只在 hover 时露出时间戳
- **DM 保留气泡**（单对单视角不变）
- **Markdown 全面渲染**（org DM + 群聊）：`react-markdown` + `remark-gfm` + `remark-breaks`，支持粗体/斜体/引用/代码块/行内代码/列表/标题/GFM 表格/任务列表/删除线；单换行保留；保留 @mention 和链接的既有点击交互；code 块内 `@` 不转换（避免 `` `mail @alice` `` 误伤）
- **粘贴上传图片**：ChatPanel（私聊）和 MyOrgPage（DM + 群聊）的 textarea 加 `onPaste`，剪贴板是图片就自动暂存待发（10MB 上限）
- **侧边栏折叠状态持久化**：组织成员 / 组织群聊两个分区的展开/收起写入 localStorage

### 修复
- **多 bot 下老 thread 报 "Not a participant"**：`_get_thread_token` 原来只取第一个 bot 的 token；改成遍历所有候选（用户的所有 instance bot + admin bot），用 `GET /api/threads/:id` 探测，返回第一个实际是 participant 的。所有 thread 端点（messages/detail/patch/leave/invite/remove/QC auto-revise）都传 thread_id 触发探测。
- 老 Local Agent DB schema 字段缺失：`instances` 表可能没 `org_id` 列（org_id 实际在 `instance_configs`）；`install_events` 列名是 `state` 不是 `event_type`。
- Local Agent `status` 字段反映真实 daemon 在线状态（GET `/api/me` 拉 bot.online）而不是创建时写死的 active
- 重命名 Local Agent 支持：`_get_agent_token` 回源到 `server_settings.local_agent_token_{id}`；跳过 docker pm2 重启步骤（没容器）
- 多组织下的 Local Agent bot 透传 avatar_url 到 `all_bots` 响应

### 文档
- README.md / README_CN.md：4 种产品介绍，新增 Local Agent 专节 + 机制说明

---

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
