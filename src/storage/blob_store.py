"""Blob store: raw document bytes — PDFs, scanned images, OCR render
artifacts, annotated markup outputs — segregated from metadata
(metadata_store.py) and embeddings (vector_store.py). Three implementations:

  - LocalDiskBlobStore (default): the sample/demo PIDs already exist as real
    files under data/samples/, so this is mostly a pass-through — but it's
    also where a document uploaded as raw bytes (rather than a path already
    on disk) would land by default, with no extra infra required.
  - MinioBlobStore: S3-compatible object storage, self-hosted via Docker
    with no cloud account needed (MinIO speaks the real S3 API, so this is
    also a drop-in for real AWS S3 later — same client, different endpoint/
    credentials). The production choice: proper content-addressed object
    storage instead of files scattered across local disk, and the natural
    home for OCR renders and markup PDFs alongside the source documents.
  - MongoGridFSBlobStore: kept as a secondary option for when raw bytes
    should live alongside the rest of the Mongo-backed metadata rather than
    in a separate object store — a smaller-scope deployment that would
    rather run one database than two storage systems.
"""

from __future__ import annotations

import hashlib
import io
from abc import ABC, abstractmethod
from pathlib import Path

from src.config import redact_uri, settings
from src.observability.logging import get_logger, log_event

logger = get_logger("storage.blob_store")


class BlobStore(ABC):
    name: str

    @abstractmethod
    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str: ...

    @abstractmethod
    def get(self, key: str) -> bytes: ...

    @abstractmethod
    def exists(self, key: str) -> bool: ...


class LocalDiskBlobStore(BlobStore):
    name = "local"

    def __init__(self):
        self._root = settings.blob_store_dir
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        # keys can contain path-unsafe characters (pid names); hash into a
        # flat, collision-resistant filename rather than nesting directories.
        safe = hashlib.sha1(key.encode()).hexdigest()
        return self._root / safe

    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        path = self._path(key)
        path.write_bytes(data)
        log_event(logger, 20, "blob_stored", key=key, backend=self.name, bytes=len(data))
        return str(path)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).exists()


class MinioBlobStore(BlobStore):
    name = "minio"

    def __init__(self, client=None):
        from minio import Minio

        self._client = client or Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )
        self._bucket = settings.minio_bucket
        if not self._client.bucket_exists(self._bucket):
            self._client.make_bucket(self._bucket)
        log_event(logger, 20, "minio_connected", endpoint=settings.minio_endpoint, bucket=self._bucket)

    @staticmethod
    def _object_name(key: str) -> str:
        # Object keys, unlike LocalDiskBlobStore's flat hashed filenames, are
        # kept human-readable (minus unsafe characters) — MinIO/S3 handle
        # arbitrary key strings natively and a readable key is genuinely
        # useful when browsing the bucket via `mc` or the MinIO console.
        return "".join(c if c.isalnum() or c in "-._/" else "_" for c in key)

    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        obj = self._object_name(key)
        self._client.put_object(self._bucket, obj, io.BytesIO(data), length=len(data), content_type=content_type)
        log_event(logger, 20, "blob_stored", key=key, backend=self.name, bytes=len(data))
        return f"s3://{self._bucket}/{obj}"

    def get(self, key: str) -> bytes:
        resp = self._client.get_object(self._bucket, self._object_name(key))
        try:
            return resp.read()
        finally:
            resp.close()
            resp.release_conn()

    def exists(self, key: str) -> bool:
        from minio.error import S3Error

        try:
            self._client.stat_object(self._bucket, self._object_name(key))
            return True
        except S3Error:
            return False


class MongoGridFSBlobStore(BlobStore):
    name = "mongo_gridfs"

    def __init__(self, client=None):
        import gridfs
        import pymongo

        self._client = client or pymongo.MongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=3000)
        self._db = self._client[settings.mongodb_db_name]
        self._fs = gridfs.GridFS(self._db)
        log_event(logger, 20, "gridfs_connected", uri=redact_uri(settings.mongodb_uri), db=settings.mongodb_db_name)

    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        if self._fs.exists({"filename": key}):
            for old in self._fs.find({"filename": key}):
                self._fs.delete(old._id)
        file_id = self._fs.put(data, filename=key, content_type=content_type)
        log_event(logger, 20, "blob_stored", key=key, backend=self.name, bytes=len(data))
        return str(file_id)

    def get(self, key: str) -> bytes:
        return self._fs.get_last_version(key).read()

    def exists(self, key: str) -> bool:
        return self._fs.exists({"filename": key})


_instance: BlobStore | None = None


def get_blob_store() -> BlobStore:
    global _instance
    if _instance is not None:
        return _instance
    backend = settings.blob_store
    try:
        if backend == "minio":
            _instance = MinioBlobStore()
        elif backend == "mongo_gridfs":
            _instance = MongoGridFSBlobStore()
        else:
            _instance = LocalDiskBlobStore()
    except Exception as exc:  # noqa: BLE001
        log_event(logger, 40, "blob_store_connect_failed_falling_back_to_local", backend=backend, error=str(exc))
        _instance = LocalDiskBlobStore()
    return _instance


def reset_blob_store_cache() -> None:
    global _instance
    _instance = None
