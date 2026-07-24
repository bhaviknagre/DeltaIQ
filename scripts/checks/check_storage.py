"""Check: the storage layer — MongoDB metadata store (chat sessions,
processing jobs, canonical docs, delta results), Redis-backed chat session
cache, MinIO blob store, and the vector store (Chroma). Each sub-check is
independent and skips (not fails) if its backend isn't reachable, since
every one of these has a working zero-infra fallback by design — this check
verifies whichever backend is actually configured/reachable behaves
correctly, not that every backend must be running.

Usage: python -m scripts.checks.check_storage
"""

from __future__ import annotations

import uuid

from scripts.checks._common import CheckSuite


def main() -> None:
    suite = CheckSuite("storage")

    # --- Metadata store (whichever backend METADATA_STORE selects) ---
    from src.storage.metadata_store import get_metadata_store

    store = get_metadata_store()
    with suite.check(f"metadata store ({store.name}): register + resolve PID"):
        pid = f"check-storage-{uuid.uuid4().hex[:8]}"
        store.register_pid(pid, "/tmp/doesnotneedtoexist.pdf", "Rev X")
        entry = store.resolve_pid(pid)
        assert entry["revision_label"] == "Rev X"

    with suite.check(f"metadata store ({store.name}): processing job lifecycle"):
        job_id = f"check-job-{uuid.uuid4().hex[:8]}"
        store.save_processing_job(job_id, {"kind": "check", "status": "running"})
        store.update_processing_job(job_id, {"status": "success", "result": {"ok": True}})
        job = store.get_processing_job(job_id)
        assert job["status"] == "success", job

    with suite.check(f"metadata store ({store.name}): chat session round-trip"):
        session_id = f"check-sess-{uuid.uuid4().hex[:8]}"
        store.append_chat_turn(session_id, {"question": "q1", "answer": "a1"})
        store.append_chat_turn(session_id, {"question": "q2", "answer": "a2"})
        turns = store.get_chat_session(session_id)
        assert [t["question"] for t in turns] == ["q1", "q2"], turns

    # --- Redis-backed chat session cache (cache-aside over the metadata store) ---
    from src.storage.session_store import get_session_store

    session_store = get_session_store()
    backend = "redis" if session_store._redis is not None else "memory (Redis unreachable)"
    with suite.check(f"chat session cache ({backend}): write + read"):
        sid = f"check-cache-{uuid.uuid4().hex[:8]}"
        session_store.append_turn(sid, "hello", "hi there", grounded=True)
        history = session_store.get_history(sid)
        assert len(history) == 1 and history[0]["question"] == "hello", history

    # --- Blob store (whichever backend BLOB_STORE selects) ---
    from src.storage.blob_store import get_blob_store

    blob_store = get_blob_store()
    with suite.check(f"blob store ({blob_store.name}): put + get round-trip"):
        key = f"check-blob-{uuid.uuid4().hex[:8]}"
        payload = b"hello from check_storage"
        blob_store.put(key, payload)
        assert blob_store.exists(key)
        assert blob_store.get(key) == payload

    # --- Vector store (only meaningful if RETRIEVAL_BACKEND != bm25) ---
    from src.config import settings

    if settings.retrieval_backend == "bm25":
        suite.skip("vector store", "RETRIEVAL_BACKEND=bm25 — vector store isn't used by default")
    else:
        from src.storage.embeddings import get_embedder
        from src.storage.vector_store import get_vector_store

        with suite.check(f"vector store ({settings.vector_store}): upsert + query round-trip"):
            vstore = get_vector_store()
            embedder = get_embedder()
            collection = f"check-vec-{uuid.uuid4().hex[:8]}"
            texts = ["26-KA-902 compressor tag", "unrelated banana text"]
            # Chroma rejects empty metadata dicts outright — {} is not a
            # valid "no metadata" value the way it is for a plain dict.
            vstore.upsert(collection, ["a", "b"], embedder.embed(texts), texts, [{"source": "check"}] * 2)
            hits = vstore.query(collection, embedder.embed_one("26-KA-902"), top_k=2)
            assert len(hits) > 0, "no hits from a freshly-upserted collection"
            vstore.delete_collection(collection)

    suite.exit()


if __name__ == "__main__":
    main()
