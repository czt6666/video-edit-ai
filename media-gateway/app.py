"""media-gateway — the only self-authored service.

It holds the real TOS / Doubao / Ark credentials so the agent never has to.
Three jobs:
  * POST /asr/submit  — workspace path -> TOS presigned URL -> Doubao ASR task
  * GET  /asr/{id}    — poll Doubao result (timestamped utterances)
  * POST /vlm         — pass images+prompt to Ark (OpenAI-compatible VLM)
Plus GET /health. Every non-health route requires `Authorization: Bearer <MG_TOKEN>`.

Doubao 录音文件识别 2.0 (bigmodel, v3 "auc"): the v3 API uses the request-id you
send as the task identifier, so this service stays stateless — submit generates a
uuid, returns it, and query just re-sends it. Header/field names follow the
public v3 spec; verify against current docs (and check vahnxu/doubao-asr's
License before copying any of its code) if a field name drifts.
"""
import os
import posixpath
import time
import uuid

import boto3
import httpx
from botocore.client import Config
from botocore.exceptions import ClientError
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

# ---- config ---------------------------------------------------------------
MG_TOKEN = os.environ["MG_TOKEN"]
TOS_BUCKET = os.environ["TOS_BUCKET"]
TOS_PREFIX = os.environ.get("TOS_PREFIX", "").lstrip("/")
DOUBAO_BASE = os.environ["DOUBAO_ASR_BASE_URL"].rstrip("/")
DOUBAO_APP_KEY = os.environ["DOUBAO_ASR_APP_KEY"]
DOUBAO_ACCESS_KEY = os.environ["DOUBAO_ASR_ACCESS_KEY"]
ARK_BASE = os.environ["ARK_BASE_URL"].rstrip("/")
ARK_KEY = os.environ["ARK_API_KEY"]
ARK_VLM_MODEL = os.environ["ARK_VLM_MODEL"]

PRESIGN_TTL = 3600           # seconds a presigned URL is valid
EXISTS_WAIT = 120            # max seconds to wait for rclone write-back
# 录音文件识别大模型 resource id. Both volc.bigasr.auc and volc.seedasr.auc are
# recognized by the API; which one is granted depends on the product you
# activate in the speech console. Override via DOUBAO_ASR_RESOURCE.
DOUBAO_RESOURCE = os.environ.get("DOUBAO_ASR_RESOURCE", "volc.bigasr.auc")

s3 = boto3.client(
    "s3",
    region_name=os.environ["TOS_REGION"],
    endpoint_url=os.environ["TOS_ENDPOINT"],
    aws_access_key_id=os.environ["TOS_ACCESS_KEY"],
    aws_secret_access_key=os.environ["TOS_SECRET_KEY"],
    config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}),
)

app = FastAPI(title="media-gateway")


# ---- auth -----------------------------------------------------------------
def auth(authorization: str = Header(default="")) -> None:
    if authorization != f"Bearer {MG_TOKEN}":
        raise HTTPException(status_code=401, detail="bad token")


# ---- path safety ----------------------------------------------------------
def to_tos_key(rel_path: str) -> str:
    """Map a /workspace-relative path to a TOS key, confined to TOS_PREFIX.

    Rejects absolute paths and any traversal that escapes the prefix.
    """
    rel = rel_path.strip().lstrip("/")
    if not rel:
        raise HTTPException(status_code=400, detail="empty path")
    key = posixpath.normpath(TOS_PREFIX + rel)
    # normpath collapses .. ; ensure we are still inside the prefix.
    if ".." in key.split("/") or (TOS_PREFIX and not key.startswith(TOS_PREFIX)):
        raise HTTPException(status_code=400, detail="path escapes prefix")
    return key


def wait_for_object(key: str) -> None:
    """Block until the object exists in TOS or EXISTS_WAIT elapses."""
    deadline = time.time() + EXISTS_WAIT
    while True:
        try:
            s3.head_object(Bucket=TOS_BUCKET, Key=key)
            return
        except ClientError as e:
            if e.response["Error"]["Code"] not in ("404", "NoSuchKey", "NotFound"):
                raise HTTPException(status_code=502, detail=f"TOS error: {e}")
            if time.time() >= deadline:
                raise HTTPException(
                    status_code=409,
                    detail=f"object not visible in TOS after {EXISTS_WAIT}s: {key}",
                )
            time.sleep(3)


def doubao_headers(request_id: str) -> dict:
    return {
        "X-Api-App-Key": DOUBAO_APP_KEY,
        "X-Api-Access-Key": DOUBAO_ACCESS_KEY,
        "X-Api-Resource-Id": DOUBAO_RESOURCE,
        "X-Api-Request-Id": request_id,
        "X-Api-Sequence": "-1",
        "Content-Type": "application/json",
    }


# ---- ASR ------------------------------------------------------------------
class AsrSubmit(BaseModel):
    path: str
    fmt: str = "wav"


@app.post("/asr/submit", dependencies=[Depends(auth)])
def asr_submit(body: AsrSubmit) -> dict:
    key = to_tos_key(body.path)
    wait_for_object(key)  # rclone write-back can lag; retry up to 120s
    url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": TOS_BUCKET, "Key": key},
        ExpiresIn=PRESIGN_TTL,
    )
    task_id = str(uuid.uuid4())
    payload = {
        "user": {"uid": "video-edit-ai"},
        "audio": {"url": url, "format": body.fmt},
        "request": {
            "model_name": "bigmodel",
            "enable_itn": True,
            "enable_punc": True,
            "show_utterances": True,
        },
    }
    r = httpx.post(
        f"{DOUBAO_BASE}/api/v3/auc/bigmodel/submit",
        headers=doubao_headers(task_id),
        json=payload,
        timeout=30,
    )
    status = r.headers.get("X-Api-Status-Code", "")
    if not status.startswith("2000000"):
        raise HTTPException(status_code=502, detail=f"doubao submit failed: {status} {r.text}")
    return {"task_id": task_id}


@app.get("/asr/{task_id}", dependencies=[Depends(auth)])
def asr_result(task_id: str) -> dict:
    r = httpx.post(
        f"{DOUBAO_BASE}/api/v3/auc/bigmodel/query",
        headers=doubao_headers(task_id),
        json={},
        timeout=30,
    )
    status = r.headers.get("X-Api-Status-Code", "")
    # 20000000 = done; 20000001/2 = still processing.
    if status == "20000000":
        result = r.json().get("result", {})
        return {"status": "done", "utterances": result.get("utterances", []),
                "text": result.get("text", "")}
    if status in ("20000001", "20000002"):
        return {"status": "processing"}
    raise HTTPException(status_code=502, detail=f"doubao query failed: {status} {r.text}")


# ---- VLM ------------------------------------------------------------------
class VlmRequest(BaseModel):
    images: list[str]          # base64-encoded JPEG/PNG bytes
    prompt: str
    model: str | None = None


@app.post("/vlm", dependencies=[Depends(auth)])
def vlm(body: VlmRequest) -> dict:
    content = [{"type": "text", "text": body.prompt}]
    for b64 in body.images:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
        })
    r = httpx.post(
        f"{ARK_BASE}/chat/completions",
        headers={"Authorization": f"Bearer {ARK_KEY}", "Content-Type": "application/json"},
        json={"model": body.model or ARK_VLM_MODEL,
              "messages": [{"role": "user", "content": content}]},
        timeout=120,
    )
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=f"ark failed: {r.status_code} {r.text}")
    data = r.json()
    return {
        "content": data["choices"][0]["message"]["content"],
        "model": data.get("model"),
        "usage": data.get("usage"),
    }


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
