import asyncio
import random
import uuid
from datetime import UTC, datetime

from celery import Task
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert

from lumen.celery_app import celery_app
from lumen.config import get_settings
from lumen.db import SessionFactory, engine, set_tenant_context
from lumen.ingestion import chunk_text, clean_text, embed_texts, extract_text
from lumen.models import Chunk, Document, IngestionJob


def _download_file(object_key: str) -> bytes:
    from lumen.documents import _s3_client

    settings = get_settings()
    return (
        _s3_client().get_object(Bucket=settings.object_store_bucket, Key=object_key)["Body"].read()
    )


async def _run_ingestion(tenant_id: uuid.UUID, document_id: uuid.UUID) -> None:
    settings = get_settings()
    try:
        async with SessionFactory() as session:
            await set_tenant_context(session, str(tenant_id))
            document = await session.scalar(
                select(Document).where(Document.id == document_id, Document.tenant_id == tenant_id)
            )
            job = await session.scalar(
                select(IngestionJob).where(
                    IngestionJob.document_id == document_id,
                    IngestionJob.tenant_id == tenant_id,
                )
            )
            if document is None or job is None:
                raise ValueError("Ingestion job or tenant-scoped document was not found")
            if document.status == "ready":
                job.state = "completed"
                await session.commit()
                return
            document.status = "processing"
            job.state = "processing"
            job.attempts += 1
            job.error_message = None
            await session.commit()

            raw = _download_file(document.object_key)
            parsed = clean_text(extract_text(document.filename, raw))
            chunks = chunk_text(parsed)
            if not chunks:
                raise ValueError("Document contains no extractable text")
            vectors = embed_texts(
                [chunk.content for chunk in chunks],
                model_name=settings.embedding_model,
                batch_size=settings.embedding_batch_size,
            )
            if any(len(vector) != 384 for vector in vectors):
                raise ValueError("Embedding model must return 384-dimensional BGE-small vectors")
            await session.execute(
                delete(Chunk).where(Chunk.tenant_id == tenant_id, Chunk.document_id == document_id)
            )
            values = [
                {
                    "id": uuid.uuid5(document_id, f"chunk:{chunk.index}"),
                    "tenant_id": tenant_id,
                    "document_id": document_id,
                    "chunk_index": chunk.index,
                    "heading": chunk.heading,
                    "content": chunk.content,
                    "embedding": vector,
                    "search_vector": func.to_tsvector("english", chunk.content),
                }
                for chunk, vector in zip(chunks, vectors, strict=True)
            ]
            statement = insert(Chunk).values(values)
            statement = statement.on_conflict_do_update(
                constraint="uq_chunk_document_index",
                set_={
                    "heading": statement.excluded.heading,
                    "content": statement.excluded.content,
                    "embedding": statement.excluded.embedding,
                    "search_vector": statement.excluded.search_vector,
                },
            )
            await session.execute(statement)
            document.status = "ready"
            job.state = "completed"
            job.error_message = None
            job.updated_at = datetime.now(UTC)
            await session.commit()
    except Exception:
        async with SessionFactory() as session:
            await set_tenant_context(session, str(tenant_id))
            document = await session.scalar(
                select(Document).where(Document.id == document_id, Document.tenant_id == tenant_id)
            )
            job = await session.scalar(
                select(IngestionJob).where(
                    IngestionJob.document_id == document_id,
                    IngestionJob.tenant_id == tenant_id,
                )
            )
            if document is not None:
                document.status = "queued"
            if job is not None:
                job.state = "pending"
                job.error_message = "Ingestion attempt failed; retry scheduled"
            await session.commit()
        raise
    finally:
        await engine.dispose()


@celery_app.task(bind=True, name="lumen.ingest_document", max_retries=5)
def ingest_document(self: Task, tenant_id: str, document_id: str) -> None:
    try:
        asyncio.run(_run_ingestion(uuid.UUID(tenant_id), uuid.UUID(document_id)))
    except Exception as exc:
        if self.request.retries >= self.max_retries:
            record_dead_letter.apply_async(
                args=[tenant_id, document_id, str(exc)[:2000]], queue="dead-letter"
            )
            return
        delay = min(300, 2**self.request.retries)
        raise self.retry(
            exc=exc,
            countdown=delay + random.uniform(0, min(30, delay * 0.25)),
        ) from exc


async def _mark_dead_letter(tenant_id: uuid.UUID, document_id: uuid.UUID, error: str) -> None:
    async with SessionFactory() as session:
        await set_tenant_context(session, str(tenant_id))
        document = await session.scalar(
            select(Document).where(Document.id == document_id, Document.tenant_id == tenant_id)
        )
        job = await session.scalar(
            select(IngestionJob).where(
                IngestionJob.document_id == document_id, IngestionJob.tenant_id == tenant_id
            )
        )
        if document:
            document.status = "failed"
            document.error_message = error
        if job:
            job.state = "dead-letter"
            job.error_message = error
            job.updated_at = datetime.now(UTC)
        await session.commit()


@celery_app.task(name="lumen.record_dead_letter")
def record_dead_letter(tenant_id: str, document_id: str, error: str) -> None:
    try:
        asyncio.run(_mark_dead_letter(uuid.UUID(tenant_id), uuid.UUID(document_id), error))
    finally:
        asyncio.run(engine.dispose())
