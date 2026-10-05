import asyncio
import hashlib
import io
import os
import re
import uuid
import zipfile
from pathlib import PurePath

import boto3
from botocore.config import Config as BotoConfig
from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from lumen.auth import Principal, get_principal
from lumen.config import get_settings
from lumen.db import get_session, set_tenant_context
from lumen.models import AuditEvent, Document, DocumentACL, IngestionJob
from lumen.tasks import ingest_document

router = APIRouter(prefix="/documents", tags=["documents"])
ALLOWED_TYPES = {
    ".pdf": {"application/pdf", "application/octet-stream"},
    ".docx": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/octet-stream",
    },
    ".txt": {"text/plain", "application/octet-stream"},
    ".md": {"text/markdown", "text/plain", "application/octet-stream"},
}


def _safe_filename(filename: str | None) -> str:
    if not filename or "\x00" in filename:
        raise HTTPException(status_code=400, detail="A valid filename is required")
    name = PurePath(filename.replace("\\", "/")).name
    name = re.sub(r"[^A-Za-z0-9._ -]", "_", name).strip(" .")
    if not name or len(name) > 255:
        raise HTTPException(status_code=400, detail="Invalid filename")
    return name


def validate_upload(filename: str, content_type: str | None, content: bytes) -> str:
    extension = os.path.splitext(filename)[1].lower()
    accepted = ALLOWED_TYPES.get(extension)
    if accepted is None:
        raise HTTPException(status_code=415, detail="Supported files are PDF, DOCX, TXT, and MD")
    if content_type and content_type.lower() not in accepted:
        raise HTTPException(status_code=415, detail="Filename extension and content type disagree")
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    if extension == ".pdf" and not content.startswith(b"%PDF-"):
        raise HTTPException(status_code=415, detail="File content is not a PDF")
    if extension == ".docx":
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                names = set(archive.namelist())
                if (
                    "[Content_Types].xml" not in names
                    or "word/document.xml" not in names
                    or sum(info.file_size for info in archive.infolist()) > 100 * 1024 * 1024
                ):
                    raise HTTPException(status_code=415, detail="Invalid or oversized DOCX archive")
        except zipfile.BadZipFile as exc:
            raise HTTPException(status_code=415, detail="File content is not a valid DOCX") from exc
    if extension in {".txt", ".md"}:
        try:
            content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=415, detail="Text files must be UTF-8 encoded") from exc
        if b"\x00" in content:
            raise HTTPException(status_code=415, detail="Text files may not contain NUL bytes")
    return extension


async def scan_with_clamav(content: bytes) -> None:
    settings = get_settings()
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(settings.clamav_host, settings.clamav_port),
            timeout=settings.clamav_timeout_seconds,
        )
        writer.write(b"zINSTREAM\x00")
        for offset in range(0, len(content), 64 * 1024):
            block = content[offset : offset + 64 * 1024]
            writer.write(len(block).to_bytes(4, "big") + block)
        writer.write(b"\x00\x00\x00\x00")
        await writer.drain()
        response = await asyncio.wait_for(reader.readline(), settings.clamav_timeout_seconds)
        writer.close()
        await writer.wait_closed()
    except (OSError, TimeoutError) as exc:
        raise HTTPException(
            status_code=503, detail="Malware scanner unavailable; upload was not accepted"
        ) from exc
    if response.endswith(b"FOUND"):
        raise HTTPException(status_code=400, detail="Uploaded file failed malware scanning")
    if not response.rstrip().endswith(b"OK"):
        raise HTTPException(status_code=503, detail="Malware scanner returned an invalid response")


def _s3_client():
    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings.object_store_endpoint,
        region_name=settings.object_store_region,
        aws_access_key_id=settings.object_store_access_key,
        aws_secret_access_key=settings.object_store_secret_key,
        config=BotoConfig(s3={"addressing_style": "path"}, retries={"max_attempts": 3}),
    )


def _store_file(object_key: str, content: bytes, content_type: str) -> None:
    settings = get_settings()
    _s3_client().put_object(
        Bucket=settings.object_store_bucket,
        Key=object_key,
        Body=content,
        ContentType=content_type,
        Metadata={"sha256": hashlib.sha256(content).hexdigest()},
    )


def _delete_file(object_key: str) -> None:
    settings = get_settings()
    _s3_client().delete_object(Bucket=settings.object_store_bucket, Key=object_key)


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    file: UploadFile = File(...),
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=128),
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    await set_tenant_context(session, str(principal.tenant_id))
    existing = await session.scalar(
        select(Document).where(
            Document.tenant_id == principal.tenant_id,
            Document.idempotency_key == idempotency_key,
        )
    )
    if existing:
        job = await session.scalar(
            select(IngestionJob).where(
                IngestionJob.tenant_id == principal.tenant_id,
                IngestionJob.document_id == existing.id,
            )
        )
        if job and job.state == "pending":
            job.state = "enqueued"
            await session.commit()
            try:
                ingest_document.apply_async(
                    args=[str(principal.tenant_id), str(existing.id)],
                    queue=tenant_queue(principal.tenant_id),
                )
            except Exception as exc:
                job.state = "pending"
                await session.commit()
                raise HTTPException(
                    status_code=503,
                    detail="Document is stored; retry with the same Idempotency-Key",
                    headers={"Retry-After": "5"},
                ) from exc
        return {"document_id": existing.id, "status": existing.status, "duplicate": True}

    settings = get_settings()
    safe_name = _safe_filename(file.filename)
    content = await file.read(settings.max_upload_bytes + 1)
    await file.close()
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="File exceeds the upload size limit")
    validate_upload(safe_name, file.content_type, content)
    await scan_with_clamav(content)

    document_id = uuid.uuid4()
    object_key = f"{principal.tenant_id}/{document_id}/{safe_name}"
    media_type = file.content_type or "application/octet-stream"
    try:
        await run_in_threadpool(_store_file, object_key, content, media_type)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Object storage is unavailable") from exc

    document = Document(
        id=document_id,
        tenant_id=principal.tenant_id,
        owner_id=principal.user_id,
        title=os.path.splitext(safe_name)[0],
        filename=safe_name,
        content_type=media_type,
        object_key=object_key,
        idempotency_key=idempotency_key,
        status="queued",
    )
    job = IngestionJob(
        id=uuid.uuid4(),
        tenant_id=principal.tenant_id,
        document_id=document_id,
        state="enqueued",
        attempts=0,
    )
    session.add_all(
        [
            document,
            job,
            DocumentACL(
                tenant_id=principal.tenant_id,
                document_id=document_id,
                principal_user_id=principal.user_id,
                permission="read",
            ),
            AuditEvent(
                tenant_id=principal.tenant_id,
                actor_id=principal.user_id,
                action="document.upload",
                resource_id=str(document_id),
            ),
        ]
    )
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        await run_in_threadpool(_delete_file, object_key)
        raise
    try:
        ingest_document.apply_async(
            args=[str(principal.tenant_id), str(document_id)],
            queue=tenant_queue(principal.tenant_id),
        )
    except Exception as exc:
        job.state = "pending"
        await session.commit()
        raise HTTPException(
            status_code=503,
            detail="Document was stored; retry this request with the same Idempotency-Key",
            headers={"Retry-After": "5"},
        ) from exc
    return {"document_id": document_id, "status": "queued", "duplicate": False}


def tenant_queue(tenant_id: uuid.UUID) -> str:
    shard = int.from_bytes(hashlib.sha256(tenant_id.bytes).digest()[:2], "big") % 16
    return f"ingest-{shard:02d}"


@router.get("")
async def list_documents(
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    await set_tenant_context(session, str(principal.tenant_id))
    rows = await session.execute(
        select(Document.id, Document.title, Document.status, Document.created_at)
        .where(Document.tenant_id == principal.tenant_id)
        .order_by(Document.created_at.desc())
        .limit(100)
    )
    return [
        {"id": row.id, "title": row.title, "status": row.status, "created_at": row.created_at}
        for row in rows
    ]


@router.get("/{document_id}")
async def get_document(
    document_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    await set_tenant_context(session, str(principal.tenant_id))
    row = await session.execute(
        select(Document, IngestionJob.state)
        .outerjoin(
            IngestionJob,
            (IngestionJob.document_id == Document.id)
            & (IngestionJob.tenant_id == principal.tenant_id),
        )
        .where(
            Document.id == document_id,
            Document.tenant_id == principal.tenant_id,
            (
                (Document.owner_id == principal.user_id)
                | select(DocumentACL.id)
                .where(
                    DocumentACL.tenant_id == principal.tenant_id,
                    DocumentACL.document_id == Document.id,
                    DocumentACL.principal_user_id == principal.user_id,
                    DocumentACL.permission == "read",
                )
                .exists()
            ),
        )
    )
    result = row.one_or_none()
    if result is None:
        raise HTTPException(status_code=404, detail="Document not found")
    document, job_state = result
    return {
        "id": document.id,
        "title": document.title,
        "status": document.status,
        "ingestion_state": job_state,
        "error": document.error_message,
        "created_at": document.created_at,
    }


@router.get("/{document_id}/events")
async def document_events(
    document_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    import json

    from fastapi.responses import StreamingResponse

    await set_tenant_context(session, str(principal.tenant_id))
    allowed = await session.scalar(
        select(Document.id).where(
            Document.id == document_id,
            Document.tenant_id == principal.tenant_id,
            (
                (Document.owner_id == principal.user_id)
                | select(DocumentACL.id)
                .where(
                    DocumentACL.tenant_id == principal.tenant_id,
                    DocumentACL.document_id == Document.id,
                    DocumentACL.principal_user_id == principal.user_id,
                    DocumentACL.permission == "read",
                )
                .exists()
            ),
        )
    )
    if allowed is None:
        raise HTTPException(status_code=404, detail="Document not found")

    async def stream():
        from lumen.db import SessionFactory

        last_event = None
        while True:
            async with SessionFactory() as stream_session:
                await set_tenant_context(stream_session, str(principal.tenant_id))
                row = await stream_session.execute(
                    select(Document.status, Document.error_message, IngestionJob.state)
                    .outerjoin(
                        IngestionJob,
                        (IngestionJob.document_id == Document.id)
                        & (IngestionJob.tenant_id == principal.tenant_id),
                    )
                    .where(Document.id == document_id, Document.tenant_id == principal.tenant_id)
                )
                state = row.one_or_none()
            if state is None:
                return
            payload = {
                "document_id": str(document_id),
                "status": state.status,
                "ingestion_state": state.state,
                "error": state.error_message,
            }
            serialized = json.dumps(payload)
            if serialized != last_event:
                yield f"event: status\ndata: {serialized}\n\n"
                last_event = serialized
            if state.status in {"ready", "failed"}:
                return
            await asyncio.sleep(1)

    return StreamingResponse(stream(), media_type="text/event-stream")
