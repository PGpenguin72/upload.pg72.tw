import asyncio
import os
import uuid

import aiofiles
from fastapi import APIRouter, Depends, File, Header, HTTPException, Request, UploadFile
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address

import database
from config import settings
from utils.email_helper import send_upload_notification
from utils.file_handler import assemble_file

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _resolve_session(x_session_token: str | None = Header(default=None)) -> dict:
    if not x_session_token:
        raise HTTPException(status_code=401, detail="Missing session token")

    import time

    session = database.get_session(x_session_token)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session token")

    code = database.get_code_by_id(session["code_id"])
    if not code or code["is_revoked"] or time.time() > code["expires_at"]:
        raise HTTPException(status_code=410, detail="Session expired or revoked")

    session["_code"] = code
    return session


# ── Routes ────────────────────────────────────────────────────────────────────

class ValidateBody(BaseModel):
    code: str


@router.post("/validate")
@limiter.limit("20/minute")
async def validate_code(request: Request, body: ValidateBody):
    import time

    code = body.code.upper().strip()
    if len(code) != 16:
        raise HTTPException(status_code=400, detail="Code must be 16 characters")

    record = database.get_code(code)
    if not record:
        raise HTTPException(status_code=404, detail="Invalid code")
    if record["is_revoked"]:
        raise HTTPException(status_code=410, detail="Code has been revoked")
    if time.time() > record["expires_at"]:
        raise HTTPException(status_code=410, detail="Code has expired")

    token = str(uuid.uuid4())
    database.create_session(token, record["id"])

    return {
        "session_token": token,
        "expires_at": record["expires_at"],
        "code": code,
    }


class InitUploadBody(BaseModel):
    filename: str
    filesize: int
    total_chunks: int


@router.post("/upload/init")
@limiter.limit("30/minute")
async def init_upload(
    request: Request,
    body: InitUploadBody,
    session: dict = Depends(_resolve_session),
):
    if body.filesize < 0:
        raise HTTPException(status_code=400, detail="Invalid filesize")
    if body.filesize > settings.max_file_size_bytes:
        raise HTTPException(status_code=413, detail="File exceeds size limit")
    if not 1 <= body.total_chunks <= 50000:
        raise HTTPException(status_code=400, detail="Invalid chunk count")
    if not body.filename or len(body.filename) > 255:
        raise HTTPException(status_code=400, detail="Invalid filename")

    upload_id = str(uuid.uuid4())
    os.makedirs(os.path.join(settings.temp_dir, upload_id), exist_ok=True)

    database.create_pending_upload(
        upload_id,
        session["code_id"],
        body.filename,
        body.total_chunks,
    )

    return {"upload_id": upload_id}


@router.put("/upload/{upload_id}/chunk/{chunk_index}")
@limiter.limit("600/minute")
async def upload_chunk(
    request: Request,
    upload_id: str,
    chunk_index: int,
    chunk: UploadFile = File(...),
    session: dict = Depends(_resolve_session),
):
    pending = database.get_pending_upload(upload_id)
    if not pending:
        raise HTTPException(status_code=404, detail="Upload session not found")
    if pending["code_id"] != session["code_id"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    if not 0 <= chunk_index < pending["total_chunks"]:
        raise HTTPException(status_code=400, detail="Chunk index out of range")

    data = await chunk.read(settings.max_chunk_size_bytes + 1)
    if len(data) > settings.max_chunk_size_bytes:
        raise HTTPException(status_code=413, detail="Chunk too large")

    chunk_path = os.path.join(settings.temp_dir, upload_id, str(chunk_index))
    async with aiofiles.open(chunk_path, "wb") as f:
        await f.write(data)

    received = len(os.listdir(os.path.join(settings.temp_dir, upload_id)))
    return {"received_chunks": received, "total_chunks": pending["total_chunks"]}


@router.post("/upload/{upload_id}/complete")
@limiter.limit("20/minute")
async def complete_upload(
    request: Request,
    upload_id: str,
    session: dict = Depends(_resolve_session),
):
    pending = database.get_pending_upload(upload_id)
    if not pending:
        raise HTTPException(status_code=404, detail="Upload session not found")
    if pending["code_id"] != session["code_id"]:
        raise HTTPException(status_code=403, detail="Forbidden")

    # Verify all chunks present
    temp_dir = os.path.join(settings.temp_dir, upload_id)
    for i in range(pending["total_chunks"]):
        if not os.path.exists(os.path.join(temp_dir, str(i))):
            raise HTTPException(status_code=400, detail=f"Missing chunk {i}")

    code = session["_code"]

    stored_filename, mime_type, file_size = await assemble_file(
        upload_id, pending["original_filename"], pending["total_chunks"], code["code"]
    )

    database.create_upload(
        pending["code_id"],
        pending["original_filename"],
        stored_filename,
        file_size,
        mime_type,
    )
    database.delete_pending_upload(upload_id)

    asyncio.create_task(
        asyncio.to_thread(
            send_upload_notification,
            code["code"],
            pending["original_filename"],
            file_size,
            stored_filename,
            mime_type,
        )
    )

    return {
        "stored_filename": stored_filename,
        "file_size": file_size,
        "mime_type": mime_type,
    }
