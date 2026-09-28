# video-edit-ai — 在线 AI 视频剪辑平台（部署仓库）

团队在浏览器里：① 在类 Finder 的文件管理器上传/整理视频；② 在聊天界面对在线 Claude Code
说「分析并剪辑 raw/…」，多轮对话出成片；③ 素材与成品都存火山引擎 TOS，多人共用。

**设计原则**：能用现成开源就用，禁止重复造轮子。Agent 像人一样直接接触视频（Bash + 完整读写）；
自研的只有一个薄服务 `media-gateway` 和三个快捷 CLI（`vasr`/`vslice`/`vsample`）。

## 架构

```
                 Internet
                    │  (edit.<域名> / files.<域名>, 共享密码)
              ┌─────▼─────┐
              │   Caddy   │  TLS + basic_auth
              └──┬─────┬──┘
       agent_net │     │ egress
   (internal, 无外网)   │
        ┌─────────┼─────┴──────────────┐
        │         │                    │
   ┌────▼───┐ ┌───▼────┐        ┌───────▼──────┐
   │ agent  │ │filebrow│        │ litellm /    │
   │(CCUI + │ │ser Q   │        │ media-gateway│──► Anthropic / TOS
   │ CLI +  │ └───┬────┘        └──────────────┘    / 豆包 / 方舟
   │ ffmpeg)│     │
   └───┬────┘     │
       │  /workspace(rw) + raw(ro)   /srv(rw)
       └──────────┴───────── /mnt/tos (host: rclone mount TOS)
```

- **宿主机**：`rclone mount` 把 TOS 挂到 `/mnt/tos`（systemd，自动重启）。
- **agent 容器**：Claude Code UI（siteboon/claudecodeui）+ Claude Code CLI + ffmpeg +
  PySceneDetect + auto-editor + 我们的 CLI + 两个 Skill。**只在 `agent_net`，无外网、无真实密钥。**
- **media-gateway**：唯一自研服务（FastAPI），持有 TOS/豆包/方舟 key。
- **litellm**：LLM 网关，持有 Anthropic key。
- **filebrowser**：FileBrowser Quantum。
- **caddy**：TLS + 共享密码前置。

真实密钥只存在于 `litellm` 与 `media-gateway`；agent 只拿到网关令牌。见验收 #6。

## 前置准备（你需要生成/申请的密钥）

| 用途 | 怎么拿 | 放进 .env |
|------|--------|-----------|
| Anthropic key | Anthropic 控制台（或先用临时 dev 网关，见下） | `ANTHROPIC_API_KEY` |
| TOS 子账号 AK/SK | 火山 IAM 建子账号 + 桶策略**仅限 `TOS_PREFIX`**（勿用 TOSFullAccess） | `TOS_ACCESS_KEY/SECRET_KEY` |
| 豆包录音识别 2.0 | 火山语音控制台，新版 API Key（App Key + Access Key） | `DOUBAO_ASR_APP_KEY/ACCESS_KEY` |
| 方舟 VLM | 火山方舟控制台，API Key + 视觉模型 endpoint（ep-…） | `ARK_API_KEY/ARK_VLM_MODEL` |
| 自己生成的令牌 | `openssl rand -hex 24` 各一个 | `LITELLM_MASTER_KEY`（sk- 开头）、`MEDIA_GATEWAY_TOKEN`、`CCUI_JWT_SECRET`(hex-32) |
| Caddy 密码哈希 | `docker run --rm caddy caddy hash-password --plaintext 'PASS'` | `CADDY_BASIC_HASH` |

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
   `LITELLM_IMAGE`、`gtstef/filebrowser` tag 已固定且非 1.82.7/1.82.8。

5. **起服务**
   ```bash
   docker compose build
   docker compose up -d
   docker compose ps
   ```

6. **首登初始化**
   - `edit.<域名>`：过 Caddy 共享密码 → claudecodeui 建**单个**账号 → 齿轮菜单里开启
     Bash/Read/Write/Edit 等工具（持久化，一次即可）→ 在 `/workspace` 根开会话。
   - `files.<域名>`：过 Caddy 密码即进（代理头认证）；若回退到密码模式，首登**立即改默认密码**。

7. **跑一遍验收**（见下）与 `docs/SPIKE.md` 的现场复核脚本。

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
| 1 | 两个域名同一棵目录树，共享密码可进 | Caddy 两子域 + 同挂 `/mnt/tos` |
| 2 | 新建/拖拽 30s 内 agent 可见，TOS key 对应 | rclone `--dir-cache-time 20s`；`s3-directory-markers` |
| 3 | ≥2GB 上传→分析→缓存→二次命中 | FileBrowser 分片；`vasr` 大小+mtime 缓存 |
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

自写文件管理器/聊天前端/EDL 版本服务/文件同步；给 ffmpeg 写 MCP 封装；改用户的风格 skill；
把真实密钥放进 agent 容器；把 git 仓库放进 rclone 挂载目录；给 agent 开外网。

## 目录结构

```
docker-compose.yml       编排（网络隔离 + 挂载）
.env.example             所有配置项与密钥模板
caddy/Caddyfile          TLS + 共享密码 + 两子域 + 代理头注入
rclone/                  rclone.conf.example + systemd 单元
litellm/config.yaml      模型别名 + master_key（禁 1.82.7/1.82.8）
media-gateway/           唯一自研服务：/asr /vlm /health（FastAPI）
agent/
  Dockerfile             CCUI + Claude CLI + ffmpeg + PySceneDetect + auto-editor
  entrypoint.sh          把只读托管内容同步进持久卷
  claude/                CLAUDE.md + settings.json(bypass) + 记忆种子
  skills/
    yingshi-jufeng-tim-editor/   用户提供的风格 skill（原样、只读）
    video-workbench/             本仓库新增：目录/缓存/CLI/协作/记忆规范
  bin/                   vasr / vslice / vsample + _vcommon.py
filebrowser/config.yaml  代理头认证 + 关命令执行 + 关注册
docs/SPIKE.md            阶段 0 可行性验证与 Plan A/B 决策
```
