"""WebSocket 广播中心 + 实时日志缓冲（供 OBS 舞台与桌面启动器共用）。"""
from __future__ import annotations

import json
import logging
import time
from collections import deque
from typing import Any

from fastapi import WebSocket


class Hub:
    def __init__(self, max_recent: int = 50, max_logs: int = 200) -> None:
        self.clients: set[WebSocket] = set()
        self.recent_danmaku: deque[dict[str, Any]] = deque(maxlen=max_recent)
        self.recent_gifts: deque[dict[str, Any]] = deque(maxlen=max_recent)
        self.logs: deque[dict[str, Any]] = deque(maxlen=max_logs)
        self.last_subtitle: dict[str, Any] = {"text": "", "speaking": False}
        self.last_draw: dict[str, Any] = {}
        self.last_music: dict[str, Any] = {}

    async def broadcast(self, msg: dict[str, Any]) -> None:
        mtype = str(msg.get("type") or "")
        if mtype == "danmaku":
            self.recent_danmaku.append(msg)
        elif mtype == "gift":
            self.recent_gifts.append(msg)
        elif mtype == "subtitle":
            self.last_subtitle = msg
        elif mtype == "draw":
            self.last_draw = msg
        elif mtype == "music":
            self.last_music = msg

        if not self.clients:
            return
        payload = json.dumps(msg, ensure_ascii=False)
        dead: list[WebSocket] = []
        for ws in list(self.clients):
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    def push_log(self, level: str, name: str, message: str) -> None:
        self.logs.append({
            "ts": time.strftime("%H:%M:%S"),
            "level": level,
            "name": name,
            "message": message,
        })

    def snapshot_for_client(self) -> list[dict[str, Any]]:
        msgs: list[dict[str, Any]] = []
        msgs.extend(list(self.recent_danmaku)[-20:])
        msgs.extend(list(self.recent_gifts)[-10:])
        if self.last_subtitle.get("text"):
            msgs.append(self.last_subtitle)
        if self.last_music:
            msgs.append(self.last_music)
        if self.last_draw:
            msgs.append(self.last_draw)
        return msgs


class HubLogHandler(logging.Handler):
    def __init__(self, hub: Hub) -> None:
        super().__init__()
        self.hub = hub

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self.hub.push_log(record.levelname, record.name, msg)
        except Exception:
            pass
