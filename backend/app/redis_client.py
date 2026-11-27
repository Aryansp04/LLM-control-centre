"""Redis subsystem for caching, ephemeral session state, rate limiting, Pub/Sub, and job locks.

Never used for permanent conversation history storage.
Handles Redis outages gracefully without crashing the API while accurately surfacing
Redis health in `/health`, `/ready`, and `/api/monitoring/overview`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any, Dict, Optional, Tuple

import redis.asyncio as aioredis

from app.config import get_settings

logger = logging.getLogger(__name__)


class RedisManager:
    def __init__(self) -> None:
        self._client: Optional[aioredis.Redis] = None
        self._redis_url: Optional[str] = None
        self._mode: str = "remote"
        # Emergency in-process fallback ONLY when Redis server is down, so rate limiting
        # and active-stream cancellation remain safe while Redis health reports degraded/unavailable.
        self._fallback_kv: Dict[str, Tuple[str, float]] = {}
        self._fallback_rate: Dict[str, list[float]] = {}
        self._active_generations: Dict[str, Dict[str, Any]] = {}
        self._cancel_events: Dict[str, asyncio.Event] = {}

    async def connect(self, redis_url: Optional[str] = None) -> None:
        settings = get_settings()
        url = (redis_url or settings.redis_url).strip()
        self._redis_url = url

        if url == "memory://vercel":
            self._client = None
            self._mode = "serverless-memory"
            return

        if url.startswith("memory://"):
            try:
                import fakeredis.aioredis

                self._client = fakeredis.aioredis.FakeRedis(decode_responses=True)
                self._mode = "memory"
            except ImportError:
                self._client = None
                self._mode = "serverless-memory"
            return

        self._mode = "remote"
        self._client = aioredis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=2.0,
            socket_timeout=2.0,
            health_check_interval=30,
        )

    async def close(self) -> None:
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:
                pass
            self._client = None

    @property
    def client(self) -> Optional[aioredis.Redis]:
        return self._client

    async def check_health(self) -> Dict[str, Any]:
        started = time.perf_counter()
        if self._client is None and self._mode != "serverless-memory":
            await self.connect()
        if self._mode == "serverless-memory":
            latency_ms = round((time.perf_counter() - started) * 1000.0, 2)
            return {
                "status": "operational",
                "healthy": True,
                "mode": self._mode,
                "latency_ms": latency_ms,
                "error": None,
            }
        try:
            assert self._client is not None
            pong = await self._client.ping()
            latency_ms = round((time.perf_counter() - started) * 1000.0, 2)
            return {
                "status": "operational" if pong else "degraded",
                "healthy": bool(pong),
                "mode": self._mode,
                "latency_ms": latency_ms,
                "error": None,
            }
        except Exception as exc:
            latency_ms = round((time.perf_counter() - started) * 1000.0, 2)
            return {
                "status": "unavailable",
                "healthy": False,
                "mode": self._mode,
                "latency_ms": latency_ms,
                "error": f"Redis unreachable ({type(exc).__name__})",
            }

    # ------------------------------------------------------------------
    # 1. Caching
    # ------------------------------------------------------------------
    async def get_json(self, key: str) -> Optional[Any]:
        try:
            if self._client is not None:
                raw = await self._client.get(f"cache:{key}")
                return json.loads(raw) if raw else None
        except Exception as exc:
            logger.warning("Redis cache get failed for %s: %s", key, type(exc).__name__)
        entry = self._fallback_kv.get(f"cache:{key}")
        if entry and entry[1] > time.time():
            return json.loads(entry[0])
        return None

    async def set_json(self, key: str, value: Any, ttl_seconds: int = 30) -> None:
        serialized = json.dumps(value, default=str)
        try:
            if self._client is not None:
                await self._client.setex(f"cache:{key}", ttl_seconds, serialized)
                return
        except Exception as exc:
            logger.warning("Redis cache set failed for %s: %s", key, type(exc).__name__)
        self._fallback_kv[f"cache:{key}"] = (serialized, time.time() + ttl_seconds)

    async def delete_cache(self, *keys: str) -> None:
        if not keys:
            return
        prefixed = [f"cache:{k}" for k in keys]
        for k in prefixed:
            self._fallback_kv.pop(k, None)
        try:
            if self._client is not None:
                await self._client.delete(*prefixed)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 2. Temporary Session State & JWT Revocation
    # ------------------------------------------------------------------
    async def revoke_token(self, jti: str, ttl_seconds: int) -> None:
        ttl = max(1, ttl_seconds)
        self._fallback_kv[f"revoked:{jti}"] = ("1", time.time() + ttl)
        try:
            if self._client is not None:
                await self._client.setex(f"revoked:{jti}", ttl, "1")
        except Exception as exc:
            logger.warning("Redis token revocation fallback engaged: %s", type(exc).__name__)

    async def is_token_revoked(self, jti: str) -> bool:
        try:
            if self._client is not None:
                val = await self._client.get(f"revoked:{jti}")
                if val is not None:
                    return True
        except Exception:
            pass
        entry = self._fallback_kv.get(f"revoked:{jti}")
        return bool(entry and entry[1] > time.time())

    # ------------------------------------------------------------------
    # 3. Sliding-Window Rate Limiting
    # ------------------------------------------------------------------
    async def check_rate_limit(
        self, bucket: str, limit: int, window_seconds: int = 60
    ) -> Tuple[bool, int, int]:
        """Returns (allowed, remaining, retry_after_seconds)."""
        now = time.time()
        window_start = now - window_seconds
        redis_key = f"rl:{bucket}"

        try:
            if self._client is not None:
                member = f"{now}:{uuid.uuid4().hex[:8]}"
                pipe = self._client.pipeline()
                pipe.zremrangebyscore(redis_key, 0, window_start)
                pipe.zcard(redis_key)
                results = await pipe.execute()
                current_count = int(results[1])
                if current_count >= limit:
                    oldest = await self._client.zrange(redis_key, 0, 0, withscores=True)
                    retry_after = (
                        max(1, int(window_seconds - (now - oldest[0][1])))
                        if oldest
                        else window_seconds
                    )
                    return False, 0, retry_after

                pipe2 = self._client.pipeline()
                pipe2.zadd(redis_key, {member: now})
                pipe2.expire(redis_key, window_seconds + 5)
                await pipe2.execute()
                return True, max(0, limit - current_count - 1), 0
        except Exception as exc:
            logger.warning("Redis rate-limit fallback engaged: %s", type(exc).__name__)

        # Local fallback sliding window
        timestamps = [t for t in self._fallback_rate.get(redis_key, []) if t > window_start]
        if len(timestamps) >= limit:
            retry_after = max(1, int(window_seconds - (now - timestamps[0])))
            self._fallback_rate[redis_key] = timestamps
            return False, 0, retry_after
        timestamps.append(now)
        self._fallback_rate[redis_key] = timestamps
        return True, max(0, limit - len(timestamps)), 0

    # ------------------------------------------------------------------
    # 4. Active Generation Tracking & Cancellation Coordination
    # ------------------------------------------------------------------
    async def register_generation(
        self,
        stream_id: str,
        user_id: str,
        provider_key: str,
        model_id: str,
        conversation_id: str,
    ) -> asyncio.Event:
        cancel_event = asyncio.Event()
        self._cancel_events[stream_id] = cancel_event
        meta = {
            "stream_id": stream_id,
            "user_id": user_id,
            "provider_key": provider_key,
            "model_id": model_id,
            "conversation_id": conversation_id,
            "started_at": time.time(),
        }
        self._active_generations[stream_id] = meta
        try:
            if self._client is not None:
                await self._client.setex(
                    f"gen:active:{stream_id}", 600, json.dumps(meta)
                )
        except Exception:
            pass
        return cancel_event

    async def cancel_generation(self, stream_id: str, user_id: str) -> bool:
        """Cancel an active generation only if owned by user_id."""
        meta = self._active_generations.get(stream_id)
        if meta and meta.get("user_id") != user_id:
            return False

        try:
            if self._client is not None:
                raw = await self._client.get(f"gen:active:{stream_id}")
                if raw:
                    stored = json.loads(raw)
                    if stored.get("user_id") != user_id:
                        return False
                    await self._client.setex(f"gen:cancel:{stream_id}", 120, "1")
                elif meta is None:
                    return False
        except Exception:
            if meta is None:
                return False

        ev = self._cancel_events.get(stream_id)
        if ev is not None:
            ev.set()
            return True
        return meta is not None

    async def is_generation_cancelled(self, stream_id: str) -> bool:
        ev = self._cancel_events.get(stream_id)
        if ev is not None and ev.is_set():
            return True
        try:
            if self._client is not None:
                flag = await self._client.get(f"gen:cancel:{stream_id}")
                if flag == "1":
                    if ev is not None:
                        ev.set()
                    return True
        except Exception:
            pass
        return False

    async def finish_generation(self, stream_id: str) -> None:
        self._active_generations.pop(stream_id, None)
        self._cancel_events.pop(stream_id, None)
        try:
            if self._client is not None:
                await self._client.delete(
                    f"gen:active:{stream_id}", f"gen:cancel:{stream_id}"
                )
        except Exception:
            pass

    async def count_active_generations(self, user_id: str) -> int:
        local_ids = {
            sid
            for sid, meta in self._active_generations.items()
            if meta.get("user_id") == user_id
        }
        try:
            if self._client is not None:
                cursor = 0
                while True:
                    cursor, keys = await self._client.scan(
                        cursor=cursor, match="gen:active:*", count=50
                    )
                    for key in keys:
                        raw = await self._client.get(key)
                        if raw:
                            data = json.loads(raw)
                            if data.get("user_id") == user_id:
                                local_ids.add(data.get("stream_id", key))
                    if cursor == 0:
                        break
        except Exception:
            pass
        return len(local_ids)

    # ------------------------------------------------------------------
    # 5. Live Event Distribution (Pub/Sub)
    # ------------------------------------------------------------------
    async def publish_user_event(self, user_id: str, event_payload: Dict[str, Any]) -> None:
        try:
            if self._client is not None:
                await self._client.publish(
                    f"events:user:{user_id}", json.dumps(event_payload, default=str)
                )
        except Exception as exc:
            logger.debug("Redis publish skipped: %s", type(exc).__name__)

    # ------------------------------------------------------------------
    # 6. Background Job Coordination Lock
    # ------------------------------------------------------------------
    async def acquire_job_lock(self, job_name: str, ttl_seconds: int = 60) -> Optional[str]:
        token = uuid.uuid4().hex
        lock_key = f"lock:{job_name}"
        try:
            if self._client is not None:
                acquired = await self._client.set(
                    lock_key, token, nx=True, ex=ttl_seconds
                )
                return token if acquired else None
        except Exception:
            pass
        existing = self._fallback_kv.get(lock_key)
        if existing and existing[1] > time.time():
            return None
        self._fallback_kv[lock_key] = (token, time.time() + ttl_seconds)
        return token

    async def release_job_lock(self, job_name: str, token: str) -> None:
        lock_key = f"lock:{job_name}"
        existing = self._fallback_kv.get(lock_key)
        if existing and existing[0] == token:
            self._fallback_kv.pop(lock_key, None)
        try:
            if self._client is not None:
                val = await self._client.get(lock_key)
                if val == token:
                    await self._client.delete(lock_key)
        except Exception:
            pass


redis_manager = RedisManager()
