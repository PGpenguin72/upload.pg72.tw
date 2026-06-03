import os
import re
import uuid
import shutil
from datetime import datetime

import aiofiles
import magic

from config import settings


def sanitize_extension(filename: str) -> str:
    parts = filename.rsplit(".", 1)
    if len(parts) == 2:
        ext = re.sub(r"[^a-zA-Z0-9]", "", parts[1])[:10].lower()
        return f".{ext}" if ext else ""
    return ""


def build_stored_filename(ext: str, code: str) -> str:
    uid = uuid.uuid4().hex
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    return f"{uid}_{timestamp}_{code}{ext}"


async def assemble_file(
    upload_id: str, original_filename: str, total_chunks: int, code: str
) -> tuple[str, str, int]:
    ext = sanitize_extension(original_filename)
    stored_filename = build_stored_filename(ext, code)
    final_path = os.path.join(settings.upload_dir, stored_filename)
    temp_dir = os.path.join(settings.temp_dir, upload_id)

    async with aiofiles.open(final_path, "wb") as out:
        for i in range(total_chunks):
            chunk_path = os.path.join(temp_dir, str(i))
            async with aiofiles.open(chunk_path, "rb") as chunk_file:
                data = await chunk_file.read()
                await out.write(data)

    file_size = os.path.getsize(final_path)
    mime_type = magic.from_file(final_path, mime=True)

    shutil.rmtree(temp_dir, ignore_errors=True)

    return stored_filename, mime_type, file_size


def cleanup_temp_dirs(max_age_seconds: int = 7200) -> None:
    import time

    now = time.time()
    if not os.path.isdir(settings.temp_dir):
        return
    for entry in os.scandir(settings.temp_dir):
        if entry.is_dir() and (now - entry.stat().st_mtime) > max_age_seconds:
            shutil.rmtree(entry.path, ignore_errors=True)
