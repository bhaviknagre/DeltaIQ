from __future__ import annotations

import json
from datetime import datetime, timezone

from src.config import redact_uri, settings
from src.observability.logging import get_logger, log_event
from src.storage.metadata_store import get_metadata_store

logger = get_logger("storage.session_store")

SESSION_TTL_SECONDS = 60 * 60 * 6  


class ChatSessionStore:
    def __init__(self):
        self._redis = None
        try:
            import redis

            client = redis.Redis.from_url(settings.redis_url, decode_responses=True, socket_connect_timeout=2)
            client.ping()
            self._redis = client
            log_event(logger, 20, "session_store_redis_connected", url=redact_uri(settings.redis_url))
        except Exception as exc:  
            log_event(logger, 30, "session_store_redis_unavailable_using_memory_fallback", error=str(exc))
            self._memory: dict[str, list[dict]] = {}

    def _key(self, session_id: str) -> str:
        return f"chat_session:{session_id}"

    def append_turn(self, session_id: str, question: str, answer: str, **meta) -> None:
        turn = {"question": question, "answer": answer, "ts": datetime.now(timezone.utc).isoformat(), **meta}

        get_metadata_store().append_chat_turn(session_id, turn) 

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
