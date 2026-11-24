"""多引擎语音合成与播放：默认免费 edge-tts，支持阿里云百炼 CosyVoice / OpenAI 兼容 TTS / Windows SAPI。"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx

from .config import ROOT_DIR

log = logging.getLogger("dfyzb.tts")

AudioHook = Callable[[bool], Awaitable[None]] | None


class TTSEngine:
    def __init__(self, cfg: dict[str, Any]) -> None:
        self.cfg = cfg
        self.cache_dir = ROOT_DIR / "data" / "tts_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        self.speaking = False
        self._mixer_ready = False

    def update_config(self, cfg: dict[str, Any]) -> None:
        self.cfg = cfg

    def _ensure_mixer(self) -> None:
        if self._mixer_ready:
            return
        import pygame

        if not pygame.mixer.get_init():
            pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=1024)
        self._mixer_ready = True

    def _cache_path(self, key_str: str, ext: str) -> Path:
        h = hashlib.sha1(key_str.encode("utf-8")).hexdigest()[:16]
        return self.cache_dir / f"tts_{h}{ext}"

    async def synthesize(self, text: str) -> Path:
        tcfg = self.cfg.get("tts") or {}
        provider = str(tcfg.get("provider") or "edge").strip().lower()
        if provider == "edge":
            return await self._synth_edge(text, tcfg)
        if provider == "cosyvoice":
            return await self._synth_cosyvoice(text, tcfg)
        if provider == "openai":
            return await self._synth_openai(text, tcfg)
        if provider == "sapi":
            return await self._synth_sapi(text)
        return await self._synth_edge(text, tcfg)

    async def _synth_edge(self, text: str, tcfg: dict[str, Any]) -> Path:
        import edge_tts

        voice = str(tcfg.get("voice") or "zh-CN-XiaoxiaoNeural").strip()
        rate = str(tcfg.get("rate") or "+5%").strip()
        volume = str(tcfg.get("volume") or "+0%").strip()
        pitch = str(tcfg.get("pitch") or "+0Hz").strip()

        out = self._cache_path(f"edge|{voice}|{rate}|{volume}|{pitch}|{text}", ".mp3")
        if out.exists() and out.stat().st_size > 200:
            return out

        comm = edge_tts.Communicate(text=text, voice=voice, rate=rate, volume=volume, pitch=pitch)
        try:
            await comm.save(str(out))
            return out
        except Exception as exc:
            log.warning("edge-tts 合成失败（%s），自动回退到 Windows 本地离线语音 SAPI", exc)
            return await self._synth_sapi(text)

    async def _synth_cosyvoice(self, text: str, tcfg: dict[str, Any]) -> Path:
        api_key = str(tcfg.get("api_key") or "").strip()
        if not api_key:
            log.warning("CosyVoice 未填写 API Key，自动回退到免费 edge-tts")
            return await self._synth_edge(text, tcfg)

        model = str(tcfg.get("cosy_model") or tcfg.get("model") or "cosyvoice-v2").strip()
        voice = str(tcfg.get("cosy_voice") or "longxiaochun_v2").strip()
        out = self._cache_path(f"cosy|{model}|{voice}|{text}", ".mp3")
        if out.exists() and out.stat().st_size > 200:
            return out

        def _run_dashscope() -> bytes:
            import dashscope
            from dashscope.audio.tts_v2 import SpeechSynthesizer

            dashscope.api_key = api_key
            synth = SpeechSynthesizer(model=model, voice=voice)
            audio = synth.call(text)
            if not audio:
                raise RuntimeError("CosyVoice 合成返回空音频")
            return bytes(audio)

        try:
            audio_bytes = await asyncio.to_thread(_run_dashscope)
            out.write_bytes(audio_bytes)
            return out
        except ImportError:
            raise RuntimeError("使用 CosyVoice 需安装 dashscope（pip install dashscope），或切换到免费的 edge-tts / OpenAI 兼容 TTS。")

    async def _synth_openai(self, text: str, tcfg: dict[str, Any]) -> Path:
        api_key = str(tcfg.get("api_key") or "").strip()
        base_url = str(tcfg.get("base_url") or "https://api.openai.com/v1").strip().rstrip("/")
        model = str(tcfg.get("openai_model") or tcfg.get("model") or "tts-1").strip()
        voice = str(tcfg.get("openai_voice") or "alloy").strip()

        out = self._cache_path(f"openai|{base_url}|{model}|{voice}|{text}", ".mp3")
        if out.exists() and out.stat().st_size > 200:
            return out

        url = base_url if base_url.endswith("/audio/speech") else f"{base_url}/audio/speech"
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        payload = {"model": model, "voice": voice, "input": text, "response_format": "mp3"}

        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(url, headers=headers, json=payload)
            if r.status_code >= 400:
                raise RuntimeError(f"OpenAI TTS 失败 HTTP {r.status_code}: {r.text[:200]}")
            out.write_bytes(r.content)
        return out

    async def _synth_sapi(self, text: str) -> Path:
        out = self._cache_path(f"sapi|{text}", ".wav")
        if out.exists() and out.stat().st_size > 200:
            return out

        safe_text = text.replace("'", "''").replace('"', " ")
        ps_script = (
            "Add-Type -AssemblyName System.Speech; "
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            f"$s.SetOutputToWaveFile('{str(out)}'); "
            f"$s.Speak('{safe_text}'); "
            "$s.Dispose();"
        )

        def _run() -> None:
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_script],
                check=True,
                capture_output=True,
                timeout=20,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )

        await asyncio.to_thread(_run)
        return out

    async def _play_file(self, path: Path) -> None:
        self._ensure_mixer()
        import pygame

        def _play_sync() -> None:
            sound = pygame.mixer.Sound(str(path))
            ch = pygame.mixer.Channel(0)
            ch.play(sound)
            deadline = time.monotonic() + max(sound.get_length() + 1.5, 2.0)
            while ch.get_busy() and time.monotonic() < deadline:
                time.sleep(0.05)

        await asyncio.to_thread(_play_sync)

    async def speak(
        self,
        text: str,
        on_state: AudioHook = None,
    ) -> None:
        text = str(text or "").strip()
        if not text:
            return
        async with self._lock:
            audio_path = await self.synthesize(text)
            self.speaking = True
            if on_state:
                await on_state(True)
            try:
                await self._play_file(audio_path)
            finally:
                self.speaking = False
                if on_state:
                    await on_state(False)
