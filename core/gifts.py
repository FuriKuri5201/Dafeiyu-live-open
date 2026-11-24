"""本场礼物统计与贡献榜。"""
from __future__ import annotations

import time
from collections import deque
from typing import Any

from .events import Event


class GiftTracker:
    def __init__(self, max_history: int = 80) -> None:
        self.history: deque[dict[str, Any]] = deque(maxlen=max_history)
        self.user_totals: dict[str, dict[str, Any]] = {}
        self.total_count: int = 0
        self.total_value: float = 0.0

    def record(self, ev: Event) -> dict[str, Any]:
        count = max(1, int(ev.count or 1))
        value = round(float(ev.price or 0.0) * count, 2)
        if value <= 0 and ev.diamond > 0:
            # 抖音音浪约 10 音浪 = 1 元（估算展示用）
            value = round((ev.diamond * count) / 10.0, 2)

        entry = {
            "user": ev.user,
            "gift": ev.gift or "礼物",
            "count": count,
            "value": value,
            "platform": ev.platform,
            "ts": time.strftime("%H:%M:%S"),
        }
        self.history.appendleft(entry)
        self.total_count += count
        self.total_value = round(self.total_value + value, 2)

        u = self.user_totals.setdefault(ev.user, {"user": ev.user, "count": 0, "value": 0.0})
        u["count"] += count
        u["value"] = round(u["value"] + value, 2)
        return entry

    def reset(self) -> None:
        self.history.clear()
        self.user_totals.clear()
        self.total_count = 0
        self.total_value = 0.0

    def snapshot(self) -> dict[str, Any]:
        board = sorted(
            self.user_totals.values(),
            key=lambda x: (x["value"], x["count"]),
            reverse=True,
        )[:10]
        return {
            "total_count": self.total_count,
            "total_value": self.total_value,
            "leaderboard": board,
            "recent": list(self.history)[:20],
        }
