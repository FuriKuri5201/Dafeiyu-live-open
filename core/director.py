"""精简版总控导演：支持独立控制每个功能模块，以及一键开播 / 停止直播。"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from .bili_collector import BilibiliCollector
from .config import load_config, save_config
from .douyin_collector import DouyinCollector
from .draw import DrawStudio
from .events import Event, clean_text
from .gifts import GiftTracker
from .hub import Hub
from .llm import LLMClient
from .music import LocalMusicPlayer
from .tts import TTSEngine
from .vts import VTSClient

log = logging.getLogger("dfyzb.director")


class Director:
    def __init__(self, hub: Hub) -> None:
        self.hub = hub
        self.cfg = load_config()

        self.llm = LLMClient(self.cfg)
        self.tts = TTSEngine(self.cfg)
        self.gifts = GiftTracker()
        self.music = LocalMusicPlayer(self.cfg, on_update=self.hub.broadcast)
        self.draw = DrawStudio(self.cfg, on_update=self.hub.broadcast, on_announce=self.say)
        self.douyin = DouyinCollector(self.cfg, on_event=self.on_event)
        self.bilibili = BilibiliCollector(self.cfg, on_event=self.on_event)
        self.vts = VTSClient(self.cfg)

        self.live_active = False
        self.chat_enabled = bool((self.cfg.get("features") or {}).get("chat", True))
        self.gift_enabled = bool((self.cfg.get("features") or {}).get("gift", True))
        self.obs_stage_enabled = bool((self.cfg.get("features") or {}).get("obs_stage", True))

        self._event_queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=200)
        self._worker_task: asyncio.Task | None = None
        self._last_reply_ts = 0.0

    def ensure_worker(self) -> None:
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._event_loop())

    def apply_config(self, new_cfg: dict[str, Any]) -> dict[str, Any]:
        self.cfg = save_config(new_cfg)
        self.llm.update_config(self.cfg)
        self.tts.update_config(self.cfg)
        self.music.update_config(self.cfg)
        self.draw.update_config(self.cfg)
        self.douyin.update_config(self.cfg)
        self.bilibili.update_config(self.cfg)
        self.vts.update_config(self.cfg)
        feats = self.cfg.get("features") or {}
        self.chat_enabled = bool(feats.get("chat", True))
        self.gift_enabled = bool(feats.get("gift", True))
        self.obs_stage_enabled = bool(feats.get("obs_stage", True))
        return self.cfg

    # -------------------- 独立功能启停 --------------------

    async def set_feature(self, name: str, enabled: bool) -> dict[str, Any]:
        self.ensure_worker()
        self.cfg.setdefault("features", {})[name] = bool(enabled)
        save_config(self.cfg)

        if name == "douyin":
            if enabled:
                ok, msg = await self.douyin.start()
                if not ok:
                    self.cfg["features"]["douyin"] = False
                    save_config(self.cfg)
                return {"ok": ok, "message": msg}
            await self.douyin.stop()
            return {"ok": True, "message": "抖音采集已停止"}

        if name == "bilibili":
            if enabled:
                ok, msg = await self.bilibili.start()
                if not ok:
                    self.cfg["features"]["bilibili"] = False
                    save_config(self.cfg)
                return {"ok": ok, "message": msg}
            await self.bilibili.stop()
            return {"ok": True, "message": "B站采集已停止"}

        if name == "music":
            if enabled:
                await self.music.start()
                return {"ok": True, "message": f"本地点歌已开启（曲库 {len(self.music.library)} 首）"}
            await self.music.stop()
            return {"ok": True, "message": "本地点歌已停止"}

        if name == "draw":
            if enabled:
                await self.draw.start()
                return {"ok": True, "message": "AI 画室已开启"}
            await self.draw.stop()
            return {"ok": True, "message": "AI 画室已停止"}

        if name == "chat":
            self.chat_enabled = bool(enabled)
            return {"ok": True, "message": "AI 语音聊天已开启" if enabled else "AI 语音聊天已暂停"}

        if name == "gift":
            self.gift_enabled = bool(enabled)
            return {"ok": True, "message": "礼物统计与答谢已开启" if enabled else "礼物统计与答谢已暂停"}

        if name == "obs_stage":
            self.obs_stage_enabled = bool(enabled)
            return {"ok": True, "message": "OBS 舞台推送已开启" if enabled else "OBS 舞台推送已暂停"}

        if name == "vts":
            if enabled:
                ok, msg = await self.vts.start()
                if not ok:
                    self.cfg["features"]["vts"] = False
                    save_config(self.cfg)
                return {"ok": ok, "message": msg}
            await self.vts.stop()
            return {"ok": True, "message": "VTube Studio 皮套接口已断开"}

        return {"ok": False, "message": f"未知功能模块: {name}"}

    # -------------------- 一键开播 / 一键停播 --------------------

    async def start_live(self) -> dict[str, Any]:
        self.ensure_worker()
        feats = self.cfg.get("features") or {}
        results: list[str] = []

        self.chat_enabled = bool(feats.get("chat", True))
        self.gift_enabled = bool(feats.get("gift", True))
        self.obs_stage_enabled = bool(feats.get("obs_stage", True))

        if feats.get("music"):
            await self.music.start()
            results.append("本地点歌")
        if feats.get("draw"):
            await self.draw.start()
            results.append("AI画室")
        if feats.get("douyin"):
            ok, msg = await self.douyin.start()
            results.append(f"抖音采集({'成功' if ok else msg})")
        if feats.get("bilibili"):
            ok, msg = await self.bilibili.start()
            results.append(f"B站采集({'成功' if ok else msg})")
        if feats.get("vts"):
            ok, msg = await self.vts.start()
            results.append(f"VTS皮套({'成功' if ok else '连接失败'})")

        self.live_active = True
        summary = "、".join(results) if results else "基础语音与舞台服务"
        log.info("🚀 一键开播已启动：%s", summary)
        return {"ok": True, "message": f"已启动：{summary}"}

    async def stop_live(self) -> dict[str, Any]:
        self.live_active = False
        await self.douyin.stop()
        await self.bilibili.stop()
        await self.music.stop()
        await self.draw.stop()
        await self.vts.stop()
        log.info("⏹ 直播已全部停止")
        return {"ok": True, "message": "所有运行中的直播模块已停止"}

    # -------------------- 语音输出 --------------------

    async def say(self, text: str) -> None:
        text = clean_text(text)
        if not text:
            return
        log.info("🎙️ 主播说话：%s", text)

        async def _on_state(speaking: bool) -> None:
            self.music.set_ducking(speaking)
            self.vts.set_speaking(speaking)
            if self.obs_stage_enabled:
                await self.hub.broadcast({
                    "type": "subtitle",
                    "text": text,
                    "speaking": speaking,
                    "streamer": (self.cfg.get("streamer") or {}).get("name", "大肥鱼AI"),
                })
                await self.hub.broadcast({
                    "type": "avatar_state",
                    "speaking": speaking,
                })

        try:
            await self.tts.speak(text, on_state=_on_state)
        except Exception as exc:
            log.warning("语音播报失败: %s", exc)
            if self.obs_stage_enabled:
                await self.hub.broadcast({"type": "subtitle", "text": text, "speaking": False})

    # -------------------- 事件接入与路由 --------------------

    async def on_event(self, ev: Event) -> None:
        self.ensure_worker()
        try:
            self._event_queue.put_nowait(ev)
        except asyncio.QueueFull:
            pass

    async def _event_loop(self) -> None:
        while True:
            ev = await self._event_queue.get()
            try:
                await self._dispatch(ev)
            except Exception as exc:
                log.warning("处理事件失败: %s", exc)

    async def _dispatch(self, ev: Event) -> None:
        if ev.kind == "comment":
            log.info("💬 [%s] %s: %s", ev.platform, ev.user, ev.text)
            if self.obs_stage_enabled:
                await self.hub.broadcast({
                    "type": "danmaku",
                    "user": ev.user,
                    "text": ev.text,
                    "platform": ev.platform,
                    "ts": time.strftime("%H:%M:%S"),
                })

            # 1) 切歌 / 点歌指令
            if self.music.running and await self._try_music_command(ev):
                return

            # 2) AI 画室指令
            if self.draw.running and await self._try_draw_command(ev):
                return

            # 3) AI 对话回复
            if self.chat_enabled:
                cooldown = float((self.cfg.get("streamer") or {}).get("reply_cooldown_sec", 3.0))
                now = time.monotonic()
                if now - self._last_reply_ts < cooldown and ev.platform != "test":
                    return
                self._last_reply_ts = now
                try:
                    reply = await self.llm.chat(ev.text, user_name=ev.user)
                    await self.say(reply)
                except Exception as exc:
                    log.warning("AI 对话回复失败: %s", exc)
                    if ev.platform == "test":
                        await self.say(f"收到{ev.user}的测试弹幕：{ev.text}。不过对话模型还没配好 Key 哦。")

        elif ev.kind == "gift":
            if not self.gift_enabled:
                return
            entry = self.gifts.record(ev)
            log.info("🎁 [%s] %s 送出 %s ×%d", ev.platform, ev.user, ev.gift, ev.count)
            if self.obs_stage_enabled:
                await self.hub.broadcast({
                    "type": "gift",
                    **entry,
                    "board": self.gifts.snapshot(),
                })
            gcfg = self.cfg.get("gift") or {}
            if gcfg.get("thank_enable", True):
                if gcfg.get("use_llm_thank"):
                    try:
                        reply = await self.llm.chat(
                            f"观众「{ev.user}」送了 {ev.count} 个「{ev.gift}」，请开心自然地感谢TA（一句话）。",
                            user_name="",
                            remember=False,
                        )
                        await self.say(reply)
                        return
                    except Exception:
                        pass
                tpl = str(gcfg.get("thank_template") or "谢谢{user}送的{count}个{gift}！")
                await self.say(tpl.format(user=ev.user, count=ev.count, gift=ev.gift))

    async def _try_music_command(self, ev: Event) -> bool:
        mcfg = self.cfg.get("music") or {}
        text = ev.text.strip()
        for kw in mcfg.get("skip_keywords") or ["切歌", "下一首"]:
            if text == kw:
                msg = await self.music.skip()
                await self.say(msg)
                return True

        for prefix in mcfg.get("trigger_prefixes") or ["点歌", "来首", "放首", "播放"]:
            if text.startswith(prefix) and len(text) > len(prefix):
                query = text[len(prefix):].strip(" ：:《》「」")
                if query:
                    _ok, msg = await self.music.request_song(query, user=ev.user)
                    await self.say(msg)
                    return True
        return False

    async def _try_draw_command(self, ev: Event) -> bool:
        dcfg = self.cfg.get("draw") or {}
        text = ev.text.strip()
        prefixes = sorted(dcfg.get("trigger_prefixes") or ["画", "画一个", "画一只", "帮我画"], key=len, reverse=True)
        for prefix in prefixes:
            if text.startswith(prefix) and len(text) > len(prefix):
                prompt = text[len(prefix):].strip(" ：:")
                if len(prompt) >= 2:
                    _ok, msg = await self.draw.enqueue(prompt, user=ev.user, force=(ev.platform == "test"))
                    await self.say(msg)
                    return True
        return False

    # -------------------- 状态快照 --------------------

    def status(self) -> dict[str, Any]:
        return {
            "live_active": self.live_active,
            "features": {
                "douyin": self.douyin.status(),
                "bilibili": self.bilibili.status(),
                "chat": {"running": self.chat_enabled, "speaking": self.tts.speaking},
                "gift": {"running": self.gift_enabled, **self.gifts.snapshot()},
                "music": self.music.status(),
                "draw": self.draw.status(),
                "vts": self.vts.status(),
                "obs_stage": {"running": self.obs_stage_enabled, "clients": len(self.hub.clients)},
            },
        }
