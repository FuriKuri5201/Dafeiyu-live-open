"""统一的直播间事件数据结构与文本清洗。"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

_SPACE_RE = re.compile(r"\s+")
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean_text(text: str) -> str:
    s = _CTRL_RE.sub("", str(text or ""))
    s = _SPACE_RE.sub(" ", s).strip()
    return s


@dataclass
class Event:
    kind: str  # comment | gift | enter | like | follow
    user: str = "观众"
    text: str = ""
    gift: str = ""
    count: int = 1
    price: float = 0.0
    diamond: int = 0
    total: int = 0
    uid: str = ""
    msg_id: str = ""
    platform: str = "test"  # douyin | bilibili | test
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "user": self.user,
            "text": self.text,
            "gift": self.gift,
            "count": self.count,
            "price": self.price,
            "diamond": self.diamond,
            "total": self.total,
            "uid": self.uid,
            "msg_id": self.msg_id,
            "platform": self.platform,
            "ts": self.ts,
        }
