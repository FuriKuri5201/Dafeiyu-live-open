"""抖音网页版直播间弹幕 / 礼物 / 进场 / 点赞采集器（Playwright WS Hook + Protobuf 解析）。"""
from __future__ import annotations

import asyncio
import base64
import gzip
import logging
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

from .config import ROOT_DIR, detect_browser_executable
from .events import Event, clean_text

log = logging.getLogger("dfyzb.douyin")

HOOK_JS = r"""
(() => {
  if (window.__dfyzbHook) return;
  window.__dfyzbHook = true;
  window.__dfyzbFrames = [];
  const Orig = window.WebSocket;
  class Patched extends Orig {
    constructor(url, protocols) {
      super(url, protocols === undefined ? undefined : protocols);
      try { this.binaryType = 'arraybuffer'; } catch (e) {}
      this.addEventListener('message', ev => {
        try {
          if (!(ev.data instanceof ArrayBuffer)) return;
          const b = new Uint8Array(ev.data);
          let s = '';
          const CH = 0x8000;
          for (let i = 0; i < b.length; i += CH) {
            s += String.fromCharCode.apply(null, b.subarray(i, i + CH));
          }
          window.__dfyzbFrames.push(btoa(s));
          if (window.__dfyzbFrames.length > 600) window.__dfyzbFrames.splice(0, 300);
        } catch (e) {}
      });
    }
  }
  window.WebSocket = Patched;
})();
"""


def _varint(buf: bytes, i: int) -> tuple[int, int]:
    shift = val = 0
    while i < len(buf):
        b = buf[i]
        i += 1
        val |= (b & 0x7F) << shift
        if not b & 0x80:
            return val, i
        shift += 7
        if shift > 63:
            break
    raise ValueError("varint")


def _fields(buf: bytes) -> list[tuple[int, int, Any]]:
    out: list[tuple[int, int, Any]] = []
    i, n = 0, len(buf)
    while i < n:
        key, i = _varint(buf, i)
        fn, wt = key >> 3, key & 7
        if wt == 0:
            v, i = _varint(buf, i)
            out.append((fn, wt, v))
        elif wt == 1:
            out.append((fn, wt, buf[i:i + 8]))
            i += 8
        elif wt == 2:
            ln, i = _varint(buf, i)
            out.append((fn, wt, buf[i:i + ln]))
            i += ln
        elif wt == 5:
            out.append((fn, wt, buf[i:i + 4]))
            i += 4
        else:
            raise ValueError(f"wire type {wt}")
    return out


def _text(b: bytes) -> str | None:
    try:
        s = b.decode("utf-8")
    except Exception:
        return None
    if s and all(c.isprintable() or c in "\n\t" for c in s):
        return s.strip()
    return None


def _meta(buf: bytes) -> dict[int, list[Any]]:
    d: dict[int, list[Any]] = {}
    try:
        for fn, _wt, val in _fields(buf):
            d.setdefault(fn, []).append(val)
    except Exception:
        pass
    return d


def _num(val: Any, default: int = 0) -> int:
    if isinstance(val, int):
        return val
    try:
        return int(val)
    except Exception:
        return default


def _first_text(buf: bytes) -> str:
    try:
        for fn, wt, val in _fields(buf):
            if fn == 3 and wt == 2:
                t = _text(val)
                if t:
                    return t
    except Exception:
        pass
    return ""


def _first_id(buf: bytes) -> str:
    best = 0
    try:
        for _fn, wt, val in _fields(buf):
            if wt == 0 and isinstance(val, int) and val > best:
                best = val
    except Exception:
        return ""
    return str(best) if best >= 10**8 else ""


def parse_push_frame(raw: bytes) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        pf = _fields(raw)
    except Exception:
        return out
    payload = b""
    headers: dict[str, str] = {}
    for fn, wt, val in pf:
        if fn == 8 and wt == 2:
            payload = val
        elif fn == 5 and wt == 2:
            try:
                kv = {f: v for f, w, v in _fields(val) if w == 2}
                k = (kv.get(1) or b"").decode("utf-8", "ignore")
                v = (kv.get(2) or b"").decode("utf-8", "ignore")
                if k:
                    headers[k] = v
            except Exception:
                pass
    if not payload:
        return out
    if headers.get("compress_type", "").lower() == "gzip":
        try:
            payload = gzip.decompress(payload)
        except Exception:
            return out
    try:
        for fn, wt, val in _fields(payload):
            if fn != 1 or wt != 2:
                continue
            method, body, msg_id = "", b"", ""
            for f, w, v in _fields(val):
                if f == 1 and w == 2:
                    method = v.decode("utf-8", "ignore")
                elif f == 2 and w == 2:
                    body = v
                elif f == 3 and w == 2:
                    msg_id = v.decode("utf-8", "ignore")
            if method:
                out.append({"method": method, "body": body, "msgId": msg_id})
    except Exception:
        pass
    return out


def decode_message(method: str, body: bytes, msg_id: str, combo_state: dict[str, tuple[int, float]]) -> Event | None:
    meta = _meta(body)
    if method == "WebcastChatMessage":
        user_raw = (meta.get(2) or [b""])[0]
        content = _text((meta.get(3) or [b""])[0]) or ""
        if not content:
            return None
        return Event(
            kind="comment",
            user=_first_text(user_raw) or "观众",
            text=clean_text(content),
            uid=_first_id(user_raw),
            msg_id=msg_id,
            platform="douyin",
        )

    if method == "WebcastGiftMessage":
        user_raw = (meta.get(7) or [b""])[0]
        gift_raw = (meta.get(15) or [b""])[0]
        user = _first_text(user_raw) or "观众"
        uid = _first_id(user_raw)

        gift_meta = _meta(gift_raw) if isinstance(gift_raw, (bytes, bytearray)) else {}
        gift_name = ""
        if gift_meta.get(16) and isinstance(gift_meta[16][0], (bytes, bytearray)):
            gift_name = _text(gift_meta[16][0]) or ""
        gift_id = _num((meta.get(2) or [0])[0], 0)
        diamond = _num((gift_meta.get(12) or [0])[0], 0)
        if diamond < 0 or diamond > 10_000_000:
            diamond = 0

        repeat = max(
            _num((meta.get(4) or [1])[0], 1),
            _num((meta.get(5) or [1])[0], 1),
            _num((meta.get(6) or [1])[0], 1),
            1,
        )
        ckey = f"{uid}|{gift_id or gift_name}"
        now = time.monotonic()
        last_r, last_t = combo_state.get(ckey, (0, 0.0))
        if now - last_t > 8.0 or repeat < last_r:
            delta = repeat
        else:
            delta = repeat - last_r
        combo_state[ckey] = (repeat, now)
        if delta <= 0:
            return None

        return Event(
            kind="gift",
            user=user,
            gift=gift_name or f"礼物#{gift_id}",
            count=delta,
            diamond=diamond,
            uid=uid,
            msg_id=msg_id,
            platform="douyin",
        )

    if method == "WebcastMemberMessage":
        user_raw = (meta.get(2) or [b""])[0]
        return Event(
            kind="enter",
            user=_first_text(user_raw) or "观众",
            uid=_first_id(user_raw),
            msg_id=msg_id,
            platform="douyin",
        )

    if method == "WebcastLikeMessage":
        user_raw = (meta.get(2) or [b""])[0]
        cnt = max(1, _num((meta.get(3) or [1])[0], 1))
        total = max(0, _num((meta.get(4) or [0])[0], 0))
        return Event(
            kind="like",
            user=_first_text(user_raw) or "观众",
            count=cnt,
            total=total,
            uid=_first_id(user_raw),
            msg_id=msg_id,
            platform="douyin",
        )

    return None


class DouyinCollector:
    def __init__(
        self,
        cfg: dict[str, Any],
        on_event: Callable[[Event], Awaitable[None]],
    ) -> None:
        self.cfg = cfg
        self.on_event = on_event
        self.running = False
        self.connected = False
        self.events_count = 0
        self.last_error = ""
        self._task: asyncio.Task | None = None
        self._pw = None
        self._ctx = None
        self._page = None
        self._seen: set[str] = set()
        self._combo: dict[str, tuple[int, float]] = {}

    def update_config(self, cfg: dict[str, Any]) -> None:
        self.cfg = cfg

    def _normalize_url(self, raw: str) -> str:
        s = str(raw or "").strip()
        if not s:
            return ""
        if s.startswith("http://") or s.startswith("https://"):
            return s
        return f"https://live.douyin.com/{s.lstrip('/')}"

    async def start(self) -> tuple[bool, str]:
        if self.running:
            return True, "抖音采集已在运行"
        ccfg = (self.cfg.get("collectors") or {}).get("douyin") or {}
        url = self._normalize_url(ccfg.get("room_url", ""))
        if not url:
            return False, "请先填写抖音直播间地址或房间号"
        self.running = True
        self.last_error = ""
        self._task = asyncio.create_task(self._run(url))
        return True, f"正在启动抖音采集：{url}"

    async def stop(self) -> None:
        self.running = False
        self.connected = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await self._close_browser()

    async def _close_browser(self) -> None:
        try:
            if self._ctx:
                await self._ctx.close()
        except Exception:
            pass
        try:
            if self._pw:
                await self._pw.stop()
        except Exception:
            pass
        self._ctx = None
        self._page = None
        self._pw = None

    async def _run(self, url: str) -> None:
        from playwright.async_api import async_playwright

        collectors_cfg = self.cfg.get("collectors") or {}
        dcfg = collectors_cfg.get("douyin") or {}
        prof_raw = Path(str(dcfg.get("profile_dir") or "profiles/douyin"))
        profile = prof_raw if prof_raw.is_absolute() else (ROOT_DIR / prof_raw)
        profile.mkdir(parents=True, exist_ok=True)
        headless = bool(dcfg.get("headless", False))
        browser_exe = detect_browser_executable(str(collectors_cfg.get("browser_path") or ""))

        try:
            self._pw = await async_playwright().start()
            self._ctx = await self._pw.chromium.launch_persistent_context(
                user_data_dir=str(profile),
                executable_path=browser_exe,
                headless=headless,
                viewport={"width": 1000, "height": 760},
                args=[
                    "--mute-audio",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-blink-features=AutomationControlled",
                ],
            )
            await self._ctx.add_init_script(HOOK_JS)
            self._page = self._ctx.pages[0] if self._ctx.pages else await self._ctx.new_page()
            await self._page.goto(url, wait_until="domcontentloaded", timeout=60000)
            self.connected = True
            log.info("抖音采集窗口已打开：%s", url)

            while self.running:
                if self._page.is_closed():
                    log.info("抖音采集页面已关闭")
                    break
                frames = await self._page.evaluate(
                    "() => { const a = window.__dfyzbFrames || []; window.__dfyzbFrames = []; return a; }"
                )
                for b64 in frames or []:
                    try:
                        raw = base64.b64decode(b64)
                    except Exception:
                        continue
                    for msg in parse_push_frame(raw):
                        mid = msg.get("msgId") or ""
                        if mid and mid in self._seen:
                            continue
                        if mid:
                            self._seen.add(mid)
                            if len(self._seen) > 4000:
                                self._seen = set(list(self._seen)[-2000:])
                        ev = decode_message(msg["method"], msg["body"], mid, self._combo)
                        if ev:
                            self.events_count += 1
                            await self.on_event(ev)
                await asyncio.sleep(0.35)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.last_error = str(exc)
            log.warning("抖音采集异常: %s", exc)
        finally:
            self.connected = False
            self.running = False
            await self._close_browser()

    def status(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "connected": self.connected,
            "events": self.events_count,
            "error": self.last_error,
        }
