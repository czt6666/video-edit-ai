# video-edit-ai — 在线 AI 视频剪辑平台（部署仓库）

团队在浏览器里：① 在类 Finder 的文件管理器上传/整理视频；② 在聊天界面对在线 Claude Code
说「分析并剪辑 raw/…」，多轮对话出成片；③ 素材与成品都存火山引擎 TOS，多人共用。

**设计原则**：能用现成开源就用，禁止重复造轮子。Agent 像人一样直接接触视频（Bash + 完整读写）。
UI 侧复用 `siteboon/claudecodeui`（平台模式）作聊天引擎；自研只有三个薄服务
（`auth-service` 账号/登录、`file-manager` 文件管理、`media-gateway` 音视频网关）与三个 CLI
（`vasr`/`vslice`/`vsample`）。

## 架构

**单域名、单登录**：所有页面都在一个域名下，由我们自己的 `auth-service` 统一认证。
Caddy 用 `forward_auth` 对每个受保护请求校验会话，再按路径分发到后端：

```
                        Internet ── https://<域名>
                             │
                       ┌─────▼─────┐   TLS + forward_auth 网关
                       │   Caddy   │────► /login, /api/auth/*  ─┐ (公开)
                       └──┬──────┬─┘                            │
             agent_net    │      │ egress                       ▼
         (internal,无外网) │      │                       ┌─────────────┐
        ┌──────────┬──────┼──────┴───────┐               │ auth-service│ 账号/会话
        │          │      │              │               │ (SQLite)    │ /admin 增删
   ┌────▼───┐ ┌────▼────┐ │        ┌─────▼──────┐         └─────────────┘
   │ agent  │ │  file-  │ │        │ litellm /  │  路由：
   │(CCUI,  │ │ manager │ │        │media-gateway│──►Anthropic/TOS   /            → agent
   │平台模式)│ └────┬────┘ │        └────────────┘   /豆包/方舟      /files,/api/files → file-manager
   └───┬────┘      │      │                                        /admin,/api/admin → auth-service
       │ /workspace(rw+raw ro)  /workspace(rw)
       └───────────┴────── /mnt/tos (host: rclone mount TOS)
```

- **宿主机**：`rclone mount` 把 TOS 挂到 `/mnt/tos`（systemd，自动重启）。
- **caddy**：唯一入口。TLS + `forward_auth` 会话校验 + 按路径分发。
- **auth-service**（自研，FastAPI+SQLite）：管理员建号的账号体系；登录发会话 Cookie；
  `/api/auth/verify` 供 Caddy `forward_auth`；`/admin` 增删账号。**无外网。**
- **file-manager**（自研，FastAPI）：类 Finder 文件管理（上传/删除/预览），全体成员可写 `/workspace`。
  路径越界防护（`safe_join`）。**无外网。**
- **agent 容器**：claudecodeui（平台模式，自身登录关闭，认证交给网关）+ Claude Code CLI +
  ffmpeg + PySceneDetect + auto-editor + 我们的 CLI + 两个 Skill。**只在 `agent_net`，无外网、无真实密钥。**
- **media-gateway**（自研）：持有 TOS/豆包/方舟 key，供 agent 调用 ASR/VLM。
- **litellm**：LLM 网关，持有 Anthropic key。

真实密钥只存在于 `litellm` 与 `media-gateway`；agent 只拿到网关令牌。见验收 #6。

## 前置准备（你需要生成/申请的密钥）

| 用途 | 怎么拿 | 放进 .env |
|------|--------|-----------|
| Anthropic key | Anthropic 控制台（或先用临时 dev 网关，见下） | `ANTHROPIC_API_KEY` |
| TOS 子账号 AK/SK | 火山 IAM 建子账号 + 桶策略**仅限 `TOS_PREFIX`**（勿用 TOSFullAccess） | `TOS_ACCESS_KEY/SECRET_KEY` |
| 豆包录音识别 2.0 | 火山语音控制台，新版 API Key（App Key + Access Key） | `DOUBAO_ASR_APP_KEY/ACCESS_KEY` |
| 方舟 VLM | 火山方舟控制台，API Key + 视觉模型 endpoint（ep-…） | `ARK_API_KEY/ARK_VLM_MODEL` |
| 自己生成的令牌 | `openssl rand -hex 24` 各一个 | `LITELLM_MASTER_KEY`（sk- 开头）、`MEDIA_GATEWAY_TOKEN` |
| 会话签名密钥 | `openssl rand -hex 32` | `AUTH_JWT_SECRET` |
| 初始管理员账号 | 自定；首启创建，之后在 `/admin` 里加人 | `AUTH_ADMIN_USER` / `AUTH_ADMIN_PASSWORD` |

> **临时 dev LLM 网关**：若暂时没有 Anthropic key，可在 `litellm/config.yaml` 里注释掉
> Anthropic 两行、启用 dev 段，并在 `.env` 填 `DEV_OPENAI_BASE_URL` /
> `DEV_OPENAI_API_KEY` / `DEV_OPENAI_MODEL`（如 `deepseek-v4-pro`）。仅用于连通性冒烟，
> 非 Claude 模型在 Claude Code 里的工具调用行为可能不完整。

## 部署步骤

1. **装 rclone 挂载（宿主机）**
   ```bash
   sudo mkdir -p /mnt/tos /data/rclone-cache /etc/rclone
   sudo cp rclone/rclone.conf.example /etc/rclone/rclone.conf   # 填 AK/SK/endpoint
   sudo cp rclone/rclone-tos.service /etc/systemd/system/
   # 编辑 service 里的 tos:BUCKET/PREFIX 与 --vfs-cache-max-size；确保 /etc/fuse.conf 打开 user_allow_other
   sudo systemctl daemon-reload && sudo systemctl enable --now rclone-tos
   ls /mnt/tos   # 能列出即成功
   ```
   让 docker 依赖该挂载：给 docker.service 加 drop-in `RequiresMountsFor=/mnt/tos`。

2. **建初始目录树（在 /mnt/tos 内）**
   ```bash
   mkdir -p /mnt/tos/{raw,analysis,projects,outputs}
   ```

3. **配置 .env**
   ```bash
   cp .env.example .env   # 按上表填全，DOMAIN 指向你的域名
   ```

4. **钉版本**：在 `agent/Dockerfile` 把 `CCUI_REF` 钉到具体 tag/commit；确认
   `LITELLM_IMAGE` 已固定且非 1.82.7/1.82.8。

5. **起服务**
   ```bash
   ./start.sh          # = docker compose up -d --build，并打印访问地址
   ./stop.sh           # 停止（保留卷）；./stop.sh --volumes 连账号/会话卷一起删
   ```

6. **首登初始化**
   - 打开 `https://<域名>/` → 跳转登录页 → 用 `.env` 里的 `AUTH_ADMIN_USER/PASSWORD` 登录。
   - `https://<域名>/admin`：管理员在此**新增/删除**成员账号。
   - `https://<域名>/files`：上传/整理素材到 TOS（全员可上传/删除）。
   - `https://<域名>/`：聊天工作台（平台模式已自动建好唯一 `/workspace` 项目，无需选项目）。

7. **跑一遍验收**（见下）与 `docs/SPIKE.md` 的现场复核脚本。

### 本地调试（免 Docker/TLS/rclone）

不方便起完整 Docker 栈时，可在本机跑我们自研的三件套（登录/文件/网关路由）：
```bash
./scripts/dev-up.sh     # 起 auth-service:8091 + file-manager:8092 + dev-router:8088
                        # dev-router 复刻了 Caddy 的 forward_auth 网关与路径分发
./scripts/dev-down.sh   # 停
```
打开 http://localhost:8088 → 登录（默认 admin / `.env` 里的密码）→ 上传、账号管理都可用。
聊天工作台涉及 WebSocket + 平台模式构建，需用 `./start.sh` 的 Docker 栈验证。

### 测试

```bash
cd auth-service  && python -m pytest    # 账号/登录/管理 CRUD/forward_auth
cd file-manager  && python -m pytest    # 路径越界防护 + 上传/删除/列目录
```

## 用法（对话示例）

```
[小明] 分析 raw/2026-09/直播.mp4
  → agent 后台跑 vasr 出转录并缓存到 analysis/…；再次分析立即命中缓存
[小明] 看 直播.mp4 的 01:12:00–01:14:00，抽 16 帧看主播情绪
  → vsample 返回逐帧描述 + 4×4 拼图路径（agent 会自己 Read 拼图）
[小明] 出一个 90 秒竖版精华的文字方案 → 改 → 出低清预览 → 改 → 定稿
  → projects/<名>/edit_vNNN.json 与 outputs/<名>/vNNN_preview.mp4 全部保留
```

## 验收标准对照

| # | 验收点 | 实现位置 |
|---|--------|----------|
| 1 | 单域名单登录（管理员建号），同一棵目录树 | Caddy `forward_auth` + `auth-service` + 同挂 `/mnt/tos` |
| 2 | 新建/拖拽 30s 内 agent 可见，TOS key 对应 | rclone `--dir-cache-time 20s`；`s3-directory-markers` |
| 3 | ≥2GB 上传→分析→缓存→二次命中 | `file-manager` 流式上传；`vasr` 大小+mtime 缓存 |
| 4 | vsample 抽帧 + VLM 情绪判断 | `vsample` + media-gateway `/vlm` |
| 5 | 多轮方案→预览→定稿，版本全留 | `video-workbench` 目录约定（只新增） |
| 6 | 容器内拿不到真实 key、写 raw/ 失败、无外网 | 网关持钥；`raw:ro`；`agent_net internal` |
| 7 | 重启后 rclone/容器自动恢复，会话可 resume | systemd `Restart` + compose `restart` + 持久卷 |

## 运维

- **日志**：`docker compose logs -f agent|litellm|media-gateway|caddy`；rclone：`journalctl -u rclone-tos -f`。
- **健康检查**：`curl -H "Authorization: Bearer $MEDIA_GATEWAY_TOKEN" http://…:8080/health`（容器内）。
- **rclone 缓存**：`--vfs-cache-max-size` 按 `/data` 磁盘设；缓存目录不要放进 TOS 挂载内。
- **重启恢复**：宿主机重启后 systemd 先挂 rclone，docker（RequiresMountsFor）再起；会话在 `agent_home` 卷里，`--resume` 可续。
- **升级 claudecodeui/LiteLLM**：改 `CCUI_REF` / `LITELLM_IMAGE` → `build` → `up -d`；升级 LiteLLM 前核对安全公告，验证 GHCR cosign 签名。
- **轮换密钥**：改 `.env` → `up -d` 重建受影响服务；agent 只需重建即可换网关令牌。

## 明确不做（防止重复造轮子）

不自写聊天前端（复用 claudecodeui 平台模式）/ EDL 版本服务 / 文件同步；不给 ffmpeg 写 MCP 封装；
不改用户的风格 skill；不把真实密钥放进 agent 容器；不把 git 仓库放进 rclone 挂载目录；不给 agent 开外网。

> 注：账号体系与文件管理是**按需自研的薄服务**（`auth-service`/`file-manager`）——为满足
> 「单域名单登录 + 管理员建号 + 全员上传/删除」的产品需求，且各自代码量小、职责单一、带单测。
> 聊天引擎仍复用 claudecodeui，不重复造轮子。

## 目录结构

```
docker-compose.yml       编排（网络隔离 + 挂载）
start.sh / stop.sh       一键起停 Docker 栈
.env.example             所有配置项与密钥模板
caddy/Caddyfile          TLS + forward_auth 网关 + 按路径分发
rclone/                  rclone.conf.example + systemd 单元
litellm/config.yaml      模型别名 + master_key（禁 1.82.7/1.82.8）
auth-service/            自研：账号/登录/管理 CRUD/forward_auth（FastAPI+SQLite）
  app/                   config/db/security/users/main
  web/                   login.html + admin.html
  tests/                 pytest（31 用例）
file-manager/            自研：文件管理 API + Finder 式 UI（FastAPI）
  app/paths.py           路径越界防护（safe_join，安全核心）
  web/index.html         上传/删除/预览页面
  tests/                 pytest（33 用例，含越界/软链逃逸）
media-gateway/           自研：/asr /vlm /health（FastAPI）
agent/
  Dockerfile             CCUI（平台模式构建）+ Claude CLI + ffmpeg + 媒体工具
  entrypoint.sh          同步只读托管内容；平台模式启动 + 建唯一 /workspace 项目
  platform-init.mjs      平台模式种子用户（关闭 CCUI 自身登录）
  claude/                CLAUDE.md + settings.json(bypass) + 记忆种子
  skills/
    yingshi-jufeng-tim-editor/   用户提供的风格 skill（原样、只读）
    video-workbench/             本仓库新增：目录/缓存/CLI/协作/记忆规范
  bin/                   vasr / vslice / vsample + _vcommon.py
scripts/dev-*.sh         本地免 Docker 调试（dev-router 复刻 Caddy 网关）
docs/SPIKE.md            阶段 0 可行性验证与 Plan A/B 决策
```
