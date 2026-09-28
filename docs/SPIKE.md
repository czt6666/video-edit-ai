# 阶段 0：可行性验证（SPIKE）

**结论：1–5 项全部通过 → 走 Plan A（本仓库即 Plan A 实现）。**

验证方法说明：本 SPIKE 的判定基于对各开源组件源码/文档/issue 的核查（下方给出来源），
以及本仓库据此写成的可运行配置。第 6–8 项依赖真实的 TOS 桶与样片，属于**部署时现场复核**项，
本文给出逐项复核脚本与预期结果；第 1–5 项（决定 Plan A/B 的关键项）已由公开证据判定通过。

| # | 项目 | 判定 | 依据 |
|---|------|------|------|
| 1 | CloudCLI 项目根设为 /workspace 并在根开会话 | ✅ PASS | `WORKSPACES_ROOT` 存在、默认 HOME、对新建项目路径做符号链接解析后的包含校验（issue #1111）。我们设 `WORKSPACES_ROOT=/workspace`，恰好规避 issue #1377（Settings 登录框硬编码 `/workspace`）。 |
| 2 | Bash/Read/Write/Edit 默认启用 + 容器内免确认 | ✅ PASS（需配置） | 工具默认关闭，齿轮菜单逐项开启并持久化到 auth DB（一次性）；底层 `claude` CLI 读取挂载的 `~/.claude/settings.json`，我们设 `permissions.defaultMode=bypassPermissions`。容器非 root，bypass 合法。 |
| 3 | ANTHROPIC_BASE_URL + ANTHROPIC_AUTH_TOKEN 通过凭证检测 | ✅ PASS | claudecodeui 原样透传给 CLI，网关/纯 key 模式行为不变（PR #1375）。 |
| 4 | 关闭自带登录 / 固定单账号；与 Caddy 密码叠加 | ✅ PASS（有取舍） | claudecodeui 有独立单账号登录 DB，无法完全关闭 → 与 Caddy 共享密码构成**双重登录**。取舍可接受：固定单账号 + 持久化 DB 卷，登录一次后 JWT 常驻。 |
| 5 | 两个浏览器打开同一会话看历史并续聊 | ✅ PASS（有取舍） | 会话存于服务端 `~/.claude`，自动发现；多浏览器可打开同一会话历史并继续。取舍：两端**同时**对同一运行中会话实时输入可能串流冲突，建议一人主控。 |
| 6 | FileBrowser Quantum：拖拽/多选/新建/≥2GB 分片/预览/缩略图/代理头认证 | ⏳ 设计通过，现场复核 | Quantum 支持分片上传、代理头认证（`auth.methods.proxy` + `header`）、视频预览。见下方复核脚本。 |
| 7 | rclone + ffmpeg：≥1h 样片首读/seek/回写/改名 | ⏳ 设计通过，现场复核 | VFS full 缓存 + `disable_http2` + 关闭 `vfs-read-chunk-streams`，见 `rclone/rclone-tos.service`。 |
| 8 | 容器内 raw/ 只读叠加生效，同时 FileBrowser 仍可上传 raw/ | ⏳ 设计通过，现场复核 | agent 用 `:ro` bind 挂 `raw/`；FileBrowser 用 rw 挂 `/srv`，写路径不同，互不影响。 |

## 关键取舍与缓解

- **双重登录（#4）**：Caddy 共享密码是"团队门禁"，claudecodeui 登录是"应用账号"。缓解：只建一个
  claudecodeui 账号并持久化 DB 卷；如需彻底单层，转 Plan B（见文末）。
- **多人实时同会话（#5）**：历史/续聊没问题；避免两端同时对**同一运行中**会话抢输入。多人协作靠
  `[名字]` 前缀 + 版本化文件（见 `video-workbench` skill）。
- **claudecodeui 未固定版本**：镜像用 `ARG CCUI_REF`，部署前必须钉到具体 tag/commit，并核对其
  `package.json` 的 start 脚本名与 `entrypoint.sh` 一致。

## 现场复核脚本（第 6–8 项）

在真实部署（rclone 已挂载 /mnt/tos、compose 已 up）后逐项执行：

**#7 rclone + ffmpeg（用 ≥1h 样片）**
```bash
# 首次读取 + seek（fast seek 到 55 分钟处抽一帧）
time ffmpeg -ss 3300 -i /mnt/tos/raw/sample_1h.mp4 -frames:v 1 -f image2 /tmp/probe.jpg
# 回写：写一个文件，10s 后确认 TOS 侧可见（media-gateway head_object 或 rclone ls）
echo hi > /mnt/tos/analysis/_writetest && sleep 15 && rclone ls tos:BUCKET/PREFIX/analysis/_writetest
# 目录改名（重点观察是否卡死；--dir-cache-time 20s 后可见）
mkdir -p /mnt/tos/_t/a && mv /mnt/tos/_t/a /mnt/tos/_t/b && ls /mnt/tos/_t
# 预期：抽帧秒级返回、回写 ~10-15s 可见、改名不卡死。
```

**#8 raw/ 只读叠加**
```bash
docker compose exec agent sh -c 'echo x > /workspace/raw/should_fail 2>&1 || echo "OK: raw is read-only"'
# 同时 FileBrowser（files 域名）上传一个文件到 raw/，30s 内在 agent 容器 ls 可见：
docker compose exec agent ls -la /workspace/raw/
```

**#6 FileBrowser**：浏览器打开 `files.<域名>` → 新建文件夹、拖拽移动、多选、上传一个 ≥2GB 视频
（观察分片进度）、点开视频预览与缩略图。代理头认证：确认无需二次输入 FileBrowser 账号即进入
（Caddy 已注入 `X-Forwarded-User`）。

## 若 1–5 出现硬伤 → Plan B（备选，未启用）

用 `claude-agent-sdk-python` 写 FastAPI + SSE 薄后端 + 极简聊天页，替换 claudecodeui；
其余组件（rclone / FileBrowser / LiteLLM / media-gateway / Skill / CLI）**完全复用**。
本仓库结构已使这一替换局部化：只需替换 `agent/` 服务，compose 网络/挂载/网关均不变。

## 来源

- claudecodeui `WORKSPACES_ROOT` / 路径校验：PR #1111、issue #1377、PR #1396（siteboon/claudecodeui）
- 凭证透传：PR #1375（siteboon/claudecodeui）
- FileBrowser Quantum 代理头认证：https://filebrowserquantum.com/en/docs/configuration/authentication/proxy/
- LiteLLM 供应链事件（禁用 1.82.7/1.82.8）：https://docs.litellm.ai/blog/security-update-march-2026
