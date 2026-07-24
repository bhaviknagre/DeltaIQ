"""Chat session store: Redis as the fast, TTL-bounded cache a live chat UI
actually reads on every turn; the metadata store (MongoDB in production,
see metadata_store.py) as the durable record every turn is also written to.
Writes go to both; reads prefer Redis and fall back to (then repopulate
from) the metadata store on a cache miss — the standard cache-aside pattern,
not a Redis-only ephemeral session that loses history on a cache eviction/
restart.

Falls back to a pure in-memory dict with no eviction when Redis isn't
reachable, so chat sessions still work with zero extra infra — same
"real backend opt-in, zero-infra default" pattern as everything else in
src/storage/ and src/chat/llm.py's MockProvider.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from src.config import settings
from src.observability.logging import get_logger, log_event
from src.storage.metadata_store import get_metadata_store

logger = get_logger("storage.session_store")

SESSION_TTL_SECONDS = 60 * 60 * 6  # 6 hours of inactivity before Redis evicts the cached copy


class ChatSessionStore:
    def __init__(self):
        self._redis = None
        try:
            import redis

            client = redis.Redis.from_url(settings.redis_url, decode_responses=True, socket_connect_timeout=2)
            client.ping()
            self._redis = client
            log_event(logger, 20, "session_store_redis_connected", url=settings.redis_url)
        except Exception as exc:  # noqa: BLE001
            log_event(logger, 30, "session_store_redis_unavailable_using_memory_fallback", error=str(exc))
            self._memory: dict[str, list[dict]] = {}

    def _key(self, session_id: str) -> str:
        return f"chat_session:{session_id}"

    def append_turn(self, session_id: str, question: str, answer: str, **meta) -> None:
        turn = {"question": question, "answer": answer, "ts": datetime.now(timezone.utc).isoformat(), **meta}

        get_metadata_store().append_chat_turn(session_id, turn)  # durable write, always

        if self._redis is not None:
            key = self._key(session_id)
            self._redis.rpush(key, json.dumps(turn, default=str))
            self._redis.expire(key, SESSION_TTL_SECONDS)
        else:
            self._memory.setdefault(session_id, []).append(turn)

    def get_history(self, session_id: str) -> list[dict]:
        if self._redis is not None:
            key = self._key(session_id)
            cached = self._redis.lrange(key, 0, -1)
            if cached:
                return [json.loads(t) for t in cached]
            # Cache miss: fall back to the durable store and repopulate Redis
            # so the next read within the TTL window doesn't miss again.
            history = get_metadata_store().get_chat_session(session_id)
            if history:
                self._redis.rpush(key, *[json.dumps(t, default=str) for t in history])
                self._redis.expire(key, SESSION_TTL_SECONDS)
            return history

        return list(self._memory.get(session_id, []))


_instance: ChatSessionStore | None = None


def get_session_store() -> ChatSessionStore:
    global _instance
    if _instance is None:
        _instance = ChatSessionStore()
    return _instance
