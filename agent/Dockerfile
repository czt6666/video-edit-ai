# Agent image: Claude Code UI + Claude Code CLI + ffmpeg + PySceneDetect +
# auto-editor + our vasr/vslice/vsample + the two Skills.
FROM node:22-bookworm-slim

# --- pin these before deploying -------------------------------------------
# claudecodeui git ref (tag or commit SHA). Do NOT ship :main to production.
ARG CCUI_REF=main
# Claude Code CLI version.
ARG CLAUDE_CODE_VERSION=latest

# --- system deps -----------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg python3 python3-pip python3-venv git ca-certificates \
      fonts-dejavu-core libfontconfig1 rsync procps \
    && rm -rf /var/lib/apt/lists/*

# --- python media tools (isolated venv on PATH) ---------------------------
RUN python3 -m venv /opt/pytools \
    && /opt/pytools/bin/pip install --no-cache-dir \
       "scenedetect[opencv]" opencv-python-headless auto-editor
ENV PATH="/opt/pytools/bin:${PATH}"

# --- Claude Code CLI -------------------------------------------------------
RUN npm install -g @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}

# --- claudecodeui (built from a pinned ref) --------------------------------
# node-pty needs a C/C++ toolchain to compile during install.
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*
# NOTE: claudecodeui pins @vscode/ripgrep 1.17.x, whose postinstall calls the
# GitHub API (403 anonymous rate-limit, and blocked in CN). 1.18.0 bundles the
# binaries in the tarball — no network call. We bump it, so `npm install`
# (not `npm ci`, which would reject the lockfile drift) is used.
RUN git clone https://github.com/siteboon/claudecodeui /opt/claudecodeui \
    && cd /opt/claudecodeui \
    && git checkout ${CCUI_REF} \
    && python3 -c "import json;d=json.load(open('package.json'));d['dependencies']['@vscode/ripgrep']='^1.18.0';json.dump(d,open('package.json','w'),indent=2)" \
    && npm install \
    && npm run build

# --- non-root user ---------------------------------------------------------
# uid 10001 must match rclone mount --uid so /workspace is writable.
RUN useradd -m -u 10001 agent

# --- our CLIs --------------------------------------------------------------
COPY bin/ /usr/local/bin/
RUN chmod +x /usr/local/bin/vasr /usr/local/bin/vslice /usr/local/bin/vsample

# --- managed claude home (synced into the volume at boot) ------------------
COPY claude/ /opt/agent/claude-home/
COPY skills/ /opt/agent/claude-home/skills/
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENV WORKSPACE_ROOT=/workspace
USER agent
WORKDIR /opt/claudecodeui
EXPOSE 3001
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
