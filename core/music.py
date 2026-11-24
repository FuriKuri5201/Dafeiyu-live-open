"""本地曲库点歌模块：扫描本地音乐目录 + 模糊匹配 + pygame 播放 + 说话自动压低伴奏。"""
from __future__ import annotations

import asyncio
import difflib
import logging
import random
import re
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from .config import ROOT_DIR

log = logging.getLogger("dfyzb.music")

AUDIO_EXTS = {".mp3", ".flac", ".wav", ".ogg", ".m4a", ".aac"}


def _norm(text: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", str(text or "").lower())


def _split_name(path: Path) -> tuple[str, str]:
    stem = path.stem.strip()
    for sep in (" - ", "-", "–", "—"):
        if sep in stem:
            a, b = stem.split(sep, 1)
            if a.strip() and b.strip():
                return a.strip(), b.strip()
    return "", stem


@dataclass
class Track:
    path: Path
    title: str
    artist: str = ""

    @property
    def label(self) -> str:
        return f"{self.artist} - {self.title}" if self.artist else self.title


class LocalMusicPlayer:
    def __init__(
        self,
        cfg: dict[str, Any],
        on_update: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> None:
        self.cfg = cfg
        self.on_update = on_update
        self.library: list[Track] = []
        self.queue: deque[dict[str, Any]] = deque()
        self.current: dict[str, Any] | None = None
        self.running = False
        self._ducked = False
        self._task: asyncio.Task | None = None
        self._mixer_ready = False
        self.scan_library()

    def update_config(self, cfg: dict[str, Any]) -> None:
        self.cfg = cfg
        self.scan_library()
        self._apply_volume()

    def _ensure_mixer(self) -> None:
        if self._mixer_ready:
            return
        import pygame

        if not pygame.mixer.get_init():
            pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=1024)
        self._mixer_ready = True

    def scan_library(self) -> int:
        mcfg = self.cfg.get("music") or {}
        raw_dirs = mcfg.get("dirs") or ["music"]
        tracks: list[Track] = []
        seen: set[str] = set()

        for d in raw_dirs:
            p = Path(str(d))
            if not p.is_absolute():
                p = ROOT_DIR / p
            if not p.exists():
                continue
            for fp in p.rglob("*"):
                if not fp.is_file() or fp.suffix.lower() not in AUDIO_EXTS:
                    continue
                key = str(fp.resolve()).lower()
                if key in seen:
                    continue
                seen.add(key)
                artist, title = _split_name(fp)
                tracks.append(Track(path=fp, title=title, artist=artist))

        self.library = tracks
        log.info("本地曲库扫描完成：共 %d 首歌曲", len(tracks))
        return len(tracks)

    def search(self, query: str) -> Track | None:
        q = _norm(query)
        if not q or not self.library:
            return None

        best: Track | None = None
        best_score = 0.0
        for t in self.library:
            nt = _norm(t.title)
            nl = _norm(t.label)
            if q == nt or q == nl:
                return t
            if q in nt or q in nl:
                score = 0.9 + (len(q) / max(len(nl), 1)) * 0.1
            else:
                score = max(
                    difflib.SequenceMatcher(None, q, nt).ratio(),
                    difflib.SequenceMatcher(None, q, nl).ratio(),
                )
            if score > best_score:
                best_score = score
                best = t

        return best if best_score >= 0.42 else None

    async def request_song(self, query: str, user: str = "观众") -> tuple[bool, str]:
        if not self.library:
            self.scan_library()
        if not self.library:
            return False, "本地曲库还是空的，请把音乐放到 music 文件夹里哦。"

        track = self.search(query)
        if not track:
            return False, f"本地曲库里没找到「{query}」呢。"

        item = {
            "title": track.title,
            "artist": track.artist,
            "label": track.label,
            "path": str(track.path),
            "requester": user,
            "added_at": time.time(),
        }
        self.queue.append(item)
        log.info("点歌入队：%s（点歌人：%s）", track.label, user)
        await self._emit_state()
        return True, f"已为{user}点播《{track.label}》"

    async def skip(self) -> str:
        if not self._mixer_ready:
            return "当前没有在播放歌曲"
        import pygame

        pygame.mixer.music.stop()
        prev = self.current["label"] if self.current else ""
        self.current = None
        await self._emit_state()
        return f"已切歌：{prev}" if prev else "已切歌"

    def set_ducking(self, ducked: bool) -> None:
        self._ducked = ducked
        self._apply_volume()

    def _apply_volume(self) -> None:
        if not self._mixer_ready:
            return
        import pygame

        mcfg = self.cfg.get("music") or {}
        vol = float(mcfg.get("duck_volume", 0.14) if self._ducked else mcfg.get("volume", 0.45))
        vol = max(0.0, min(1.0, vol))
        try:
            pygame.mixer.music.set_volume(vol)
        except Exception:
            pass

    async def start(self) -> None:
        if self.running:
            return
        self.scan_library()
        self.running = True
        self._task = asyncio.create_task(self._loop())
        await self._emit_state()

    async def stop(self) -> None:
        self.running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._mixer_ready:
            import pygame

            try:
                pygame.mixer.music.stop()
            except Exception:
                pass
        self.current = None
        await self._emit_state()

    async def _loop(self) -> None:
        while self.running:
            try:
                busy = False
                if self._mixer_ready:
                    import pygame

                    busy = bool(pygame.mixer.music.get_busy())

                if not busy:
                    next_item = None
                    if self.queue:
                        next_item = self.queue.popleft()
                    elif bool((self.cfg.get("music") or {}).get("auto_next", True)) and self.library:
                        t = random.choice(self.library)
                        next_item = {
                            "title": t.title,
                            "artist": t.artist,
                            "label": t.label,
                            "path": str(t.path),
                            "requester": "自动电台",
                            "added_at": time.time(),
                        }

                    if next_item:
                        self._play_item(next_item)
                        await self._emit_state()
                    elif self.current is not None:
                        self.current = None
                        await self._emit_state()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("点歌播放异常: %s", exc)
            await asyncio.sleep(0.8)

    def _play_item(self, item: dict[str, Any]) -> None:
        self._ensure_mixer()
        import pygame

        pygame.mixer.music.load(item["path"])
        self._apply_volume()
        pygame.mixer.music.play()
        self.current = item
        log.info("正在播放：%s（点歌人：%s）", item["label"], item["requester"])

    def status(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "library_count": len(self.library),
            "current": self.current,
            "queue": list(self.queue)[:15],
        }

    async def _emit_state(self) -> None:
        if self.on_update:
            await self.on_update({"type": "music", **self.status()})
