"""Metadata store: the source of truth for PID registry, cached canonical
documents, delta results, chat sessions, processing jobs, and eval run
history — segregated from the vector store (embeddings, Chroma/Pinecone)
and the blob store (raw file bytes, local disk/MinIO). One interface, two
implementations:

  - JsonFileMetadataStore: the original pid_store.json behavior, zero infra.
    Default, so `make run`/`make eval` keep working with nothing extra
    installed or running.
  - MongoMetadataStore: real MongoDB, six collections (pids,
    canonical_documents, delta_results, chat_sessions, processing_jobs,
    eval_runs). The production option — flexible schema fits documents/
    delta-items naturally, and it's the obvious place to query "every delta
    run for this PID pair," "every eval run in the last week," or "history
    of this chat session" once there's more than a handful of PIDs.

Chat sessions are also cache-fronted by Redis (src/storage/session_store.py)
for hot-path reads — Mongo is the durable record, Redis is what a live chat
UI actually reads on every turn. Processing jobs mirror Celery task
lifecycle (src/tasks/jobs.py) into a durable record independent of the
Celery result backend's TTL, so "what ran, when, with what result" survives
longer than Celery's own bookkeeping is meant to.

Selected via METADATA_STORE=json|mongo (src/config.py). ingest/pid_store.py
delegates to whichever is configured — nothing else in the codebase talks
to a specific backend directly.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

from src.config import redact_uri, settings
from src.observability.logging import get_logger, log_event

logger = get_logger("storage.metadata_store")


class MetadataStore(ABC):
    name: str

    @abstractmethod
    def register_pid(self, pid: str, path: str, revision_label: str | None) -> None: ...

    @abstractmethod
    def resolve_pid(self, pid: str) -> dict: ...

    @abstractmethod
    def list_pids(self) -> dict[str, dict]: ...

    @abstractmethod
    def save_canonical_document(self, pid: str, doc_json: dict) -> None: ...

    @abstractmethod
    def get_canonical_document(self, pid: str) -> dict | None: ...

    @abstractmethod
    def save_delta_result(self, pid_a: str, pid_b: str, delta_json: dict) -> None: ...

    @abstractmethod
    def get_delta_result(self, pid_a: str, pid_b: str) -> dict | None: ...

    @abstractmethod
    def save_eval_run(self, payload: dict) -> None: ...

    @abstractmethod
    def list_eval_runs(self, limit: int = 10) -> list[dict]: ...

    @abstractmethod
    def append_chat_turn(self, session_id: str, turn: dict) -> None: ...

    @abstractmethod
    def get_chat_session(self, session_id: str) -> list[dict]: ...

    @abstractmethod
    def save_processing_job(self, job_id: str, job: dict) -> None: ...

    @abstractmethod
    def update_processing_job(self, job_id: str, updates: dict) -> None: ...

    @abstractmethod
    def get_processing_job(self, job_id: str) -> dict | None: ...

    @abstractmethod
    def list_processing_jobs(self, limit: int = 20) -> list[dict]: ...


class PidNotFoundError(KeyError):
    pass


class JsonFileMetadataStore(MetadataStore):
    """Original behavior: one JSON file for the PID manifest. Canonical
    documents/delta results/eval runs are cached to sibling JSON files under
    the same directory rather than held in memory, so this remains a real
    (if simple) persistent store, not just a dict that vanishes on restart."""

    name = "json"

    def __init__(self):
        self._pid_path = settings.pid_store_path
        self._cache_dir = settings.pid_store_path.parent / "cache"
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def _load_manifest(self) -> dict:
        if not self._pid_path.exists():
            return {}
        return json.loads(self._pid_path.read_text())

    def _save_manifest(self, manifest: dict) -> None:
        self._pid_path.write_text(json.dumps(manifest, indent=2))

    def register_pid(self, pid: str, path: str, revision_label: str | None) -> None:
        manifest = self._load_manifest()
        manifest[pid] = {"path": path, "revision_label": revision_label}
        self._save_manifest(manifest)

    def resolve_pid(self, pid: str) -> dict:
        manifest = self._load_manifest()
        if pid not in manifest:
            raise PidNotFoundError(f"Unknown PID: {pid}")
        return manifest[pid]

    def list_pids(self) -> dict[str, dict]:
        return self._load_manifest()

    def save_canonical_document(self, pid: str, doc_json: dict) -> None:
        (self._cache_dir / f"doc_{pid}.json").write_text(json.dumps(doc_json))

    def get_canonical_document(self, pid: str) -> dict | None:
        path = self._cache_dir / f"doc_{pid}.json"
        return json.loads(path.read_text()) if path.exists() else None

    def save_delta_result(self, pid_a: str, pid_b: str, delta_json: dict) -> None:
        (self._cache_dir / f"delta_{pid_a}__{pid_b}.json").write_text(json.dumps(delta_json))

    def get_delta_result(self, pid_a: str, pid_b: str) -> dict | None:
        path = self._cache_dir / f"delta_{pid_a}__{pid_b}.json"
        return json.loads(path.read_text()) if path.exists() else None

    def save_eval_run(self, payload: dict) -> None:
        runs_path = self._cache_dir / "eval_runs.jsonl"
        with runs_path.open("a") as f:
            f.write(json.dumps(payload, default=str) + "\n")

    def list_eval_runs(self, limit: int = 10) -> list[dict]:
        runs_path = self._cache_dir / "eval_runs.jsonl"
        if not runs_path.exists():
            return []
        lines = runs_path.read_text().splitlines()[-limit:]
        return [json.loads(line) for line in lines]

    def append_chat_turn(self, session_id: str, turn: dict) -> None:
        # Embeds session_id into the record itself, matching MongoMetadataStore
        # — callers/tests can read it back from either backend the same way.
        path = self._cache_dir / f"session_{session_id}.jsonl"
        with path.open("a") as f:
            f.write(json.dumps({"session_id": session_id, **turn}, default=str) + "\n")

    def get_chat_session(self, session_id: str) -> list[dict]:
        path = self._cache_dir / f"session_{session_id}.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines()]

    def save_processing_job(self, job_id: str, job: dict) -> None:
        (self._cache_dir / f"job_{job_id}.json").write_text(json.dumps({"job_id": job_id, **job}, default=str))

    def update_processing_job(self, job_id: str, updates: dict) -> None:
        path = self._cache_dir / f"job_{job_id}.json"
        job = json.loads(path.read_text()) if path.exists() else {"job_id": job_id}
        job.update(updates)
        path.write_text(json.dumps(job, default=str))

    def get_processing_job(self, job_id: str) -> dict | None:
        path = self._cache_dir / f"job_{job_id}.json"
        return json.loads(path.read_text()) if path.exists() else None

    def list_processing_jobs(self, limit: int = 20) -> list[dict]:
        jobs = [json.loads(p.read_text()) for p in self._cache_dir.glob("job_*.json")]
        jobs.sort(key=lambda j: j.get("created_at", ""), reverse=True)
        return jobs[:limit]


class MongoMetadataStore(MetadataStore):
    """Real MongoDB-backed store — the source of truth. Six collections:
    pids, canonical_documents, delta_results, chat_sessions, processing_jobs,
    eval_runs — each a natural fit for Mongo's document model (nested
    Element/DeltaItem/chat-turn structures don't need flattening the way a
    relational schema would require)."""

    name = "mongo"

    def __init__(self, client=None):
        import pymongo

        self._client = client or pymongo.MongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=3000)
        self._db = self._client[settings.mongodb_db_name]
        self._pids = self._db["pids"]
        self._docs = self._db["canonical_documents"]
        self._deltas = self._db["delta_results"]
        self._evals = self._db["eval_runs"]
        self._chat_sessions = self._db["chat_sessions"]
        self._jobs = self._db["processing_jobs"]
        self._pids.create_index("pid", unique=True)
        self._docs.create_index("pid", unique=True)
        self._deltas.create_index([("pid_a", 1), ("pid_b", 1)], unique=True)
        self._chat_sessions.create_index("session_id")
        self._jobs.create_index("job_id", unique=True)
        log_event(logger, 20, "mongo_metadata_store_connected", uri=redact_uri(settings.mongodb_uri), db=settings.mongodb_db_name)

    def register_pid(self, pid: str, path: str, revision_label: str | None) -> None:
        self._pids.update_one(
            {"pid": pid},
            {"$set": {"pid": pid, "path": path, "revision_label": revision_label,
                      "updated_at": datetime.now(timezone.utc)}},
            upsert=True,
        )

    def resolve_pid(self, pid: str) -> dict:
        doc = self._pids.find_one({"pid": pid}, {"_id": 0})
        if doc is None:
            raise PidNotFoundError(f"Unknown PID: {pid}")
        return {"path": doc["path"], "revision_label": doc.get("revision_label")}

    def list_pids(self) -> dict[str, dict]:
        return {
            d["pid"]: {"path": d["path"], "revision_label": d.get("revision_label")}
            for d in self._pids.find({}, {"_id": 0})
        }

    def save_canonical_document(self, pid: str, doc_json: dict) -> None:
        self._docs.update_one({"pid": pid}, {"$set": {"pid": pid, "doc": doc_json}}, upsert=True)

    def get_canonical_document(self, pid: str) -> dict | None:
        rec = self._docs.find_one({"pid": pid}, {"_id": 0})
        return rec["doc"] if rec else None

    def save_delta_result(self, pid_a: str, pid_b: str, delta_json: dict) -> None:
        self._deltas.update_one(
            {"pid_a": pid_a, "pid_b": pid_b},
            {"$set": {"pid_a": pid_a, "pid_b": pid_b, "delta": delta_json,
                      "computed_at": datetime.now(timezone.utc)}},
            upsert=True,
        )

    def get_delta_result(self, pid_a: str, pid_b: str) -> dict | None:
        rec = self._deltas.find_one({"pid_a": pid_a, "pid_b": pid_b}, {"_id": 0})
        return rec["delta"] if rec else None

    def save_eval_run(self, payload: dict) -> None:
        self._evals.insert_one({**payload, "saved_at": datetime.now(timezone.utc)})

    def list_eval_runs(self, limit: int = 10) -> list[dict]:
        # Sort by _id (MongoDB ObjectIds are monotonically increasing per
        # insert), not the "saved_at" timestamp field: two runs saved within
        # the same microsecond (easily possible — eval runs are saved right
        # after each other in a script) would tie on "saved_at" and MongoDB
        # doesn't guarantee stable ordering for ties, silently scrambling
        # run history. _id has no such collision even at identical wall-clock
        # time. Excluding _id from the returned projection is independent of
        # sorting by it.
        docs = list(self._evals.find({}, {"_id": 0}).sort("_id", -1).limit(limit))
        return list(reversed(docs))

    def append_chat_turn(self, session_id: str, turn: dict) -> None:
        self._chat_sessions.insert_one({"session_id": session_id, **turn, "saved_at": datetime.now(timezone.utc)})

    def get_chat_session(self, session_id: str) -> list[dict]:
        # Same _id-not-timestamp reasoning as list_eval_runs above.
        docs = list(self._chat_sessions.find({"session_id": session_id}, {"_id": 0}).sort("_id", 1))
        return docs

    def save_processing_job(self, job_id: str, job: dict) -> None:
        self._jobs.update_one(
            {"job_id": job_id},
            {"$set": {"job_id": job_id, **job, "created_at": datetime.now(timezone.utc)}},
            upsert=True,
        )

    def update_processing_job(self, job_id: str, updates: dict) -> None:
        self._jobs.update_one(
            {"job_id": job_id},
            {"$set": {**updates, "updated_at": datetime.now(timezone.utc)}},
            upsert=True,
        )

    def get_processing_job(self, job_id: str) -> dict | None:
        return self._jobs.find_one({"job_id": job_id}, {"_id": 0})

    def list_processing_jobs(self, limit: int = 20) -> list[dict]:
        docs = list(self._jobs.find({}, {"_id": 0}).sort("_id", -1).limit(limit))
        return list(reversed(docs))


_instance: MetadataStore | None = None


def get_metadata_store() -> MetadataStore:
    global _instance
    if _instance is not None:
        return _instance
    if settings.metadata_store == "mongo":
        try:
            _instance = MongoMetadataStore()
        except Exception as exc:  # noqa: BLE001
            log_event(logger, 40, "mongo_connect_failed_falling_back_to_json", error=str(exc))
            _instance = JsonFileMetadataStore()
    else:
        _instance = JsonFileMetadataStore()
    return _instance


def reset_metadata_store_cache() -> None:
    """Test-only: clears the module-level singleton so a new store (or a
    fresh mongomock client) can be injected between test runs."""
    global _instance
    _instance = None
