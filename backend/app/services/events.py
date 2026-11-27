"""Live Event Hub & Authenticated Per-User WebSocket Manager (Module 5).

Supports:
- Strictly authenticated & user-isolated WebSocket streams
- Live status changes, generation progress, new API request events, provider errors
- Sequence-numbered frames + replay buffer for seamless client reconnection recovery
- Periodic heartbeat frames & Redis Pub/Sub cross-worker fan-out
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional, Set

from fastapi import WebSocket
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import MonitoringEvent
from app.redis_client import redis_manager

logger = logging.getLogger(__name__)


class LiveEventHub:
    def __init__(self) -> None:
        self._connections: Dict[str, Set[WebSocket]] = {}
        self._recent_events: Dict[str, Deque[Dict[str, Any]]] = {}
        self._sequence: Dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def connect(
        self, user_id: str, websocket: WebSocket, last_seq: int = 0
    ) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.setdefault(user_id, set()).add(websocket)
            current_seq = self._sequence.get(user_id, 0)
            missed = [
                ev
                for ev in self._recent_events.get(user_id, deque())
                if int(ev.get("seq", 0)) > last_seq
            ]

        await websocket.send_json(
            {
                "type": "connection_ready",
                "seq": current_seq,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "recovered_count": len(missed) if last_seq > 0 else 0,
            }
        )
        if last_seq > 0 and missed:
            for ev in missed:
                await websocket.send_json(ev)

    async def disconnect(self, user_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            conns = self._connections.get(user_id)
            if conns and websocket in conns:
                conns.remove(websocket)
                if not conns:
                    self._connections.pop(user_id, None)

    def count_connections(self, user_id: Optional[str] = None) -> int:
        if user_id is not None:
            return len(self._connections.get(user_id, set()))
        return sum(len(s) for s in self._connections.values())

    async def emit(
        self,
        *,
        user_id: str,
        event_type: str,
        title: str,
        message: str,
        severity: str = "info",
        provider_key: Optional[str] = None,
        model_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        db: Optional[AsyncSession] = None,
        persist: bool = True,
    ) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        event_id = str(uuid.uuid4())

        async with self._lock:
            seq = self._sequence.get(user_id, 0) + 1
            self._sequence[user_id] = seq
            envelope: Dict[str, Any] = {
                "id": event_id,
                "seq": seq,
                "type": event_type,
                "severity": severity,
                "provider_key": provider_key,
                "model_id": model_id,
                "title": title,
                "message": message,
                "payload": payload or {},
                "timestamp": now.isoformat(),
            }
            buf = self._recent_events.setdefault(user_id, deque(maxlen=100))
            buf.append(envelope)
            targets: List[WebSocket] = list(self._connections.get(user_id, set()))

        if persist and db is not None:
            try:
                db.add(
                    MonitoringEvent(
                        id=uuid.UUID(event_id),
                        user_id=uuid.UUID(user_id),
                        event_type=event_type,
                        severity=severity,
                        provider_key=provider_key,
                        model_id=model_id,
                        title=title,
                        message=message,
                        payload_json=payload or {},
                        created_at=now,
                    )
                )
                await db.commit()
            except Exception as exc:
                logger.warning("Could not persist monitoring event: %s", type(exc).__name__)
                await db.rollback()

        await redis_manager.publish_user_event(user_id, envelope)

        stale: List[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_json(envelope)
            except Exception:
                stale.append(ws)

        for ws in stale:
            await self.disconnect(user_id, ws)

        return envelope

    async def send_heartbeat(self, user_id: str, websocket: WebSocket) -> None:
        await websocket.send_json(
            {
                "type": "heartbeat",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "server_time_ms": int(time.time() * 1000),
            }
        )


live_event_hub = LiveEventHub()
