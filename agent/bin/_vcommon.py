"""Shared helpers for vasr / vslice / vsample. Stdlib only (few-deps rule)."""
import json
import os
import subprocess
import sys
import unicodedata
import urllib.error
import urllib.request

WORKSPACE = os.environ.get("WORKSPACE_ROOT", "/workspace")
MG_URL = os.environ.get("MEDIA_GATEWAY_URL", "").rstrip("/")
MG_TOKEN = os.environ.get("MEDIA_GATEWAY_TOKEN", "")
FONT = os.environ.get("VSAMPLE_FONT", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")


def eprint(*a):
    print(*a, file=sys.stderr, flush=True)


def normalize_existing(path):
    """Return the first of {as-is, NFC, NFD} that exists on disk."""
    for cand in (path, unicodedata.normalize("NFC", path), unicodedata.normalize("NFD", path)):
        if os.path.exists(cand):
            return cand
    return path


def cache_token(video):
    st = os.stat(video)
    return f"{st.st_size}-{int(st.st_mtime)}"


def analysis_dir(video):
    name = os.path.basename(video)
    return os.path.join(WORKSPACE, "analysis", f"{name}__{cache_token(video)}")


def ensure_meta(adir, video):
    os.makedirs(adir, exist_ok=True)
    meta = os.path.join(adir, "meta.json")
    if not os.path.isfile(meta):
        with open(meta, "w") as f:
            json.dump({"video": video, "token": cache_token(video)}, f,
                      ensure_ascii=False, indent=2)


def resolve_video(arg):
    """Accept a video file OR an existing analysis dir; return (video_abs, analysis_dir)."""
    p = arg if os.path.isabs(arg) else os.path.join(WORKSPACE, arg)
    p = normalize_existing(p)
    if os.path.isdir(p):
        meta = os.path.join(p, "meta.json")
        if os.path.isfile(meta):
            with open(meta) as f:
                return json.load(f)["video"], p
        raise SystemExit(f"not an analysis dir (no meta.json): {p}")
    if not os.path.isfile(p):
        raise SystemExit(f"file not found: {arg}")
    return p, analysis_dir(p)


def rel_to_workspace(path):
    return os.path.relpath(os.path.abspath(path), WORKSPACE)


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, **kw)


def ffprobe_duration(video):
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", video])
    return float(out.strip())


def hms(sec):
    sec = int(sec)
    return f"{sec // 3600:02d}:{(sec % 3600) // 60:02d}:{sec % 60:02d}"


def parse_ts(s):
    """Accept SS, MM:SS, HH:MM:SS, or a float number of seconds."""
    if s is None:
        return None
    if ":" in str(s):
        parts = [float(x) for x in str(s).split(":")]
        while len(parts) < 3:
            parts.insert(0, 0)
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return float(s)


def _mg(method, path, payload):
    if not MG_URL:
        raise SystemExit("MEDIA_GATEWAY_URL not set")
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        MG_URL + path, data=data, method=method,
        headers={"Authorization": f"Bearer {MG_TOKEN}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise SystemExit(f"media-gateway {method} {path} -> {e.code}: "
                         f"{e.read().decode(errors='replace')}")


def mg_post(path, payload):
    return _mg("POST", path, payload)


def mg_get(path):
    return _mg("GET", path, None)
