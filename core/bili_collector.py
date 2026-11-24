"""B 站网页版直播间弹幕 / 礼物采集器（Playwright WS 截获 + DOM 兜底）。"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import struct
import time
import zlib
from pathlib import Path
from typing import Any, Awaitable, Callable

from .config import ROOT_DIR, detect_browser_executable
from .events import Event, clean_text

log = logging.getLogger("dfyzb.bilibili")


class BilibiliCollector:
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
        self._parse_task: asyncio.Task | None = None
        self._dom_task: asyncio.Task | None = None
        self._queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=2000)
        self._pw = None
        self._ctx = None
        self._page = None
        self._recent: dict[str, float] = {}
        self._combo: dict[str, int] = {}
        self._dom_seen: set[str] = set()
        self._dom_baseline = False
        self._ws_seen: set[int] = set()

    def update_config(self, cfg: dict[str, Any]) -> None:
        self.cfg = cfg

    async def start(self) -> tuple[bool, str]:
        if self.running:
            return True, "B站采集已在运行"
        bcfg = (self.cfg.get("collectors") or {}).get("bilibili") or {}
        room_id = str(bcfg.get("room_id") or "").strip()
        if not room_id:
            return False, "请先填写 B站直播间房间号"
        self.running = True
        self.last_error = ""
        self._task = asyncio.create_task(self._run(room_id))
        return True, f"正在启动 B站采集：房间 {room_id}"

    async def stop(self) -> None:
        self.running = False
        self.connected = False
        for t in (self._parse_task, self._dom_task, self._task):
            if t:
                t.cancel()
                try:
                    await t
                except asyncio.CancelledError:
                    pass
        self._parse_task = None
        self._dom_task = None
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

    async def _run(self, room_id: str) -> None:
        from playwright.async_api import async_playwright

        collectors_cfg = self.cfg.get("collectors") or {}
        bcfg = collectors_cfg.get("bilibili") or {}
        prof_raw = Path(str(bcfg.get("profile_dir") or "profiles/bilibili"))
        profile = prof_raw if prof_raw.is_absolute() else (ROOT_DIR / prof_raw)
        profile.mkdir(parents=True, exist_ok=True)
        headless = bool(bcfg.get("headless", False))
        browser_exe = detect_browser_executable(str(collectors_cfg.get("browser_path") or ""))

        try:
            self._pw = await async_playwright().start()
            self._ctx = await self._pw.chromium.launch_persistent_context(
                user_data_dir=str(profile),
                executable_path=browser_exe,
                headless=headless,
                viewport={"width": 1100, "height": 760},
                args=[
                    "--mute-audio",
                    "--no-first-run",
                    "--no-default-browser-check",
                ],
            )
            self._page = self._ctx.pages[0] if self._ctx.pages else await self._ctx.new_page()
            self._ctx.on("websocket", self._on_websocket)
            self._page.on("websocket", self._on_websocket)

            url = room_id if room_id.startswith("http") else f"https://live.bilibili.com/{room_id}"
            await self._page.goto(url, wait_until="domcontentloaded", timeout=60000)
            self._dom_seen.clear()
            self._dom_baseline = False
            self.connected = True
            log.info("B站采集窗口已打开：%s", url)

            self._parse_task = asyncio.create_task(self._parse_loop())
            self._dom_task = asyncio.create_task(self._dom_loop())

            while self.running:
                if self._page.is_closed():
                    log.info("B站采集页面已关闭")
                    break
                await asyncio.sleep(1.5)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.last_error = str(exc)
            log.warning("B站采集异常: %s", exc)
        finally:
            self.connected = False
            self.running = False
            for t in (self._parse_task, self._dom_task):
                if t:
                    t.cancel()
            await self._close_browser()

    def _on_websocket(self, ws) -> None:
        try:
            url = str(ws.url or "")
        except Exception:
            return
        if "/sub" not in url:
            return
        ident = id(ws)
        if ident in self._ws_seen:
            return
        self._ws_seen.add(ident)
        ws.on("framereceived", self._on_frame)

    def _on_frame(self, payload) -> None:
        if isinstance(payload, bytes):
            try:
                self._queue.put_nowait(payload)
            except Exception:
                pass

    async def _parse_loop(self) -> None:
        while self.running:
            raw = await self._queue.get()
            try:
                await self._handle_packet(raw)
            except Exception:
                pass

    async def _handle_packet(self, raw: bytes) -> None:
        if len(raw) < 16:
            return
        total, hlen, ver, op, _seq = struct.unpack(">IHHII", raw[:16])
        if total < 16 or total > len(raw) or op != 5:
            return
        body = raw[hlen:total]
        if ver == 3:
            try:
                import brotli

                body = brotli.decompress(body)
            except Exception:
                return
        elif ver == 2:
            try:
                body = zlib.decompress(body)
            except Exception:
                return
        if body:
            await self._handle_messages(body)

    async def _handle_messages(self, body: bytes) -> None:
        if len(body) >= 16:
            try:
                total, hlen, _ver, _op, _seq = struct.unpack(">IHHII", body[:16])
                if 16 <= total <= len(body) and hlen >= 16:
                    await self._handle_packet(body[:total])
                    if total < len(body):
                        await self._handle_messages(body[total:])
                    return
            except Exception:
                pass

        text = body.decode("utf-8", errors="replace").strip("\x00\r\n\t ")
        try:
            data = json.loads(text)
        except Exception:
            return
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            cmd = str(item.get("cmd") or "").split(":", 1)[0]
            if cmd == "DANMU_MSG":
                await self._on_danmu(item)
            elif cmd == "SEND_GIFT":
                await self._on_gift(item)
            elif cmd == "SUPER_CHAT_MESSAGE":
                await self._on_sc(item)

    def _dedupe(self, key: str, ttl: float = 10.0) -> bool:
        now = time.monotonic()
        if now - self._recent.get(key, 0.0) < ttl:
            return True
        self._recent[key] = now
        if len(self._recent) > 3000:
            cut = now - ttl
            self._recent = {k: v for k, v in self._recent.items() if v > cut}
        return False

    async def _emit(self, ev: Event) -> None:
        self.events_count += 1
        await self.on_event(ev)

    async def _on_danmu(self, data: dict[str, Any]) -> None:
        info = data.get("info") or []
        try:
            text = clean_text(str(info[1] or ""))
            uid = str(info[2][0]) if len(info) > 2 else ""
            user = str(info[2][1]) if len(info) > 2 else "观众"
        except Exception:
            return
        if not text or self._dedupe(f"ct:{user}\x00{text}", 8.0):
            return
        await self._emit(Event(kind="comment", user=user, text=text, uid=f"bili:{uid}", platform="bilibili"))

    async def _on_gift(self, data: dict[str, Any]) -> None:
        d = data.get("data") or {}
        try:
            uid = str(d.get("uid") or "")
            user = str(d.get("uname") or "观众")
            gift = str(d.get("giftName") or d.get("gift_name") or "礼物")
            gift_id = str(d.get("giftId") or d.get("gift_id") or gift)
            num = max(1, int(d.get("num") or 1))
            combo_num = int(d.get("combo_num") or 0)
            coin_type = str(d.get("coin_type") or "gold")
            total_coin = float(d.get("total_coin") or 0.0)
            price_gold = float(d.get("price") or 0.0)
        except Exception:
            return

        if combo_num > 0:
            key = f"bili:{uid}|{gift_id}"
            last = self._combo.get(key, 0)
            count = combo_num - last if combo_num > last else 0
            self._combo[key] = combo_num
            if count <= 0:
                return
        else:
            h = hashlib.md5(json.dumps(d, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]
            if self._dedupe(f"g:{h}", 20.0):
                return
            count = num

        unit_cny = 0.0
        if coin_type == "gold":
            unit_cny = (total_coin / 1000.0 / count) if total_coin > 0 else (price_gold / 1000.0)

        await self._emit(
            Event(kind="gift", user=user, gift=gift, count=count, price=unit_cny, uid=f"bili:{uid}", platform="bilibili")
        )

    async def _on_sc(self, data: dict[str, Any]) -> None:
        d = data.get("data") or {}
        user = str((d.get("user_info") or {}).get("uname") or "观众")
        text = clean_text(str(d.get("message") or ""))
        price = float(d.get("price") or 0.0)
        await self._emit(Event(kind="gift", user=user, gift="醒目留言", count=1, price=price, platform="bilibili"))
        if text:
            await self._emit(Event(kind="comment", user=user, text=text, platform="bilibili"))

    async def _dom_loop(self) -> None:
        while self.running:
            await asyncio.sleep(1.2)
            try:
                if not self._page or self._page.is_closed():
                    continue
                items = await self._page.evaluate("""() => {
                    const el = document.querySelector('#chat-items');
                    if (!el) return [];
                    return [...el.children].slice(-30).map(c => {
                        if (!c.dataset.dfyzbId) {
                            window.__dfyzbSeq = (window.__dfyzbSeq || 0) + 1;
                            c.dataset.dfyzbId = String(window.__dfyzbSeq);
                        }
                        return {id: c.dataset.dfyzbId, cls: String(c.className || ''), text: (c.innerText || '').trim()};
                    });
                }""")
                first = not self._dom_baseline
                for item in items or []:
                    mid = str(item.get("id") or "")
                    if not mid or mid in self._dom_seen:
                        continue
                    self._dom_seen.add(mid)
                    if first:
                        continue
                    cls = str(item.get("cls") or "")
                    text = str(item.get("text") or "").strip()
                    if "danmaku-item" in cls and "\n" in text:
                        user, content = text.split("\n", 1)
                        user = user.strip().rstrip(":：").strip()
                        content = clean_text(content)
                        if user and content and not self._dedupe(f"ct:{user}\x00{content}", 8.0):
                            await self._emit(Event(kind="comment", user=user, text=content, platform="bilibili"))
                    elif "gift" in cls.lower():
                        m = re.match(r"(.+?)\s*(?:投喂|赠送|送出)\s*(.+?)(?:\s*[×xX*]\s*(\d+))?\s*$", text)
                        if m:
                            await self._emit(
                                Event(
                                    kind="gift",
                                    user=m.group(1).strip().rstrip(":："),
                                    gift=m.group(2).strip(),
                                    count=max(1, int(m.group(3) or 1)),
                                    platform="bilibili",
                                )
                            )
                if first:
                    self._dom_baseline = True
            except asyncio.CancelledError:
                raise
            except Exception:
                pass

    def status(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "connected": self.connected,
            "events": self.events_count,
            "error": self.last_error,
        }
