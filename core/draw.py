"""AI 画室模块：支持阿里云通义万相（Wanx）与任意 OpenAI 兼容文生图接口。"""
from __future__ import annotations

import asyncio
import base64
import logging
import time
from collections import deque
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx

from .config import ROOT_DIR

log = logging.getLogger("dfyzb.draw")


class DrawStudio:
    def __init__(
        self,
        cfg: dict[str, Any],
        on_update: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        on_announce: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        self.cfg = cfg
        self.on_update = on_update
        self.on_announce = on_announce
        self.out_dir = ROOT_DIR / "data" / "draws"
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=20)
        self.history: deque[dict[str, Any]] = deque(maxlen=20)
        self.current: dict[str, Any] | None = None
        self.running = False
        self._task: asyncio.Task | None = None
        self._last_req_ts = 0.0

    def update_config(self, cfg: dict[str, Any]) -> None:
        self.cfg = cfg

    def _resolve_api_key(self) -> str:
        dcfg = self.cfg.get("draw") or {}
        key = str(dcfg.get("api_key") or "").strip()
        if not key and bool(dcfg.get("reuse_tts_key", True)):
            key = str((self.cfg.get("tts") or {}).get("api_key") or "").strip()
        return key

    async def start(self) -> None:
        if self.running:
            return
        self.running = True
        self._task = asyncio.create_task(self._worker())
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
        await self._emit_state()

    async def enqueue(self, prompt: str, user: str = "观众", force: bool = False) -> tuple[bool, str]:
        dcfg = self.cfg.get("draw") or {}
        cooldown = float(dcfg.get("cooldown_sec", 15))
        now = time.monotonic()
        if not force and (now - self._last_req_ts) < cooldown:
            return False, "画室冷却中，稍后再点画哦~"

        if not self._resolve_api_key():
            return False, "AI 画室未配置 API Key（可在启动器填写画室 Key 或复用百炼 TTS Key）。"

        self._last_req_ts = now
        job = {
            "id": f"draw_{int(time.time() * 1000)}",
            "user": user,
            "prompt": prompt.strip(),
            "status": "queued",
            "image_url": "",
            "ts": time.strftime("%H:%M:%S"),
        }
        try:
            self.queue.put_nowait(job)
        except asyncio.QueueFull:
            return False, "画室排队满啦，等这批画完再来吧！"

        await self._emit_state()
        return True, f"收到{user}的点画「{prompt}」，开始动笔啦！"

    async def _worker(self) -> None:
        while self.running:
            try:
                job = await self.queue.get()
                self.current = {**job, "status": "drawing"}
                await self._emit_state()
                try:
                    filename = await self._generate(job["prompt"], job["id"])
                    done = {
                        **job,
                        "status": "done",
                        "image_url": f"/draws/{filename}",
                    }
                    self.history.appendleft(done)
                    self.current = done
                    await self._emit_state()
                    if self.on_announce:
                        await self.on_announce(f"{job['user']}点的「{job['prompt']}」画好啦，快看屏幕！")
                except Exception as exc:
                    log.warning("AI 画室出图失败: %s", exc)
                    self.current = {**job, "status": "error", "error": str(exc)}
                    await self._emit_state()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("AI 画室循环异常: %s", exc)

    async def _generate(self, prompt: str, job_id: str) -> str:
        dcfg = self.cfg.get("draw") or {}
        provider = str(dcfg.get("provider") or "wanx").strip().lower()
        style = str(dcfg.get("style_prompt") or "").strip()
        full_prompt = f"{prompt}，{style}" if style else prompt

        if provider == "openai":
            return await self._gen_openai(full_prompt, job_id, dcfg)
        return await self._gen_wanx(full_prompt, job_id, dcfg)

    async def _gen_wanx(self, prompt: str, job_id: str, dcfg: dict[str, Any]) -> str:
        api_key = self._resolve_api_key()
        base = str(dcfg.get("base_url") or "https://dashscope.aliyuncs.com/api/v1").strip().rstrip("/")
        model = str(dcfg.get("model") or "wanx2.1-t2i-turbo").strip()
        size = str(dcfg.get("size") or "1024*1024").strip()

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "X-DashScope-Async": "enable",
        }
        body = {
            "model": model,
            "input": {"prompt": prompt},
            "parameters": {"size": size, "n": 1},
        }
        async with httpx.AsyncClient(timeout=45.0) as cli:
            r = await cli.post(f"{base}/services/aigc/text2image/image-synthesis", headers=headers, json=body)
            if r.status_code >= 400:
                raise RuntimeError(f"通义万相提交失败 HTTP {r.status_code}: {r.text[:200]}")
            task_id = ((r.json().get("output") or {}).get("task_id")) or ""
            if not task_id:
                raise RuntimeError("通义万相未返回 task_id")

            img_url = ""
            for _ in range(45):
                await asyncio.sleep(1.5)
                q = await cli.get(f"{base}/tasks/{task_id}", headers={"Authorization": f"Bearer {api_key}"})
                out = (q.json().get("output") or {})
                st = str(out.get("task_status") or "")
                if st == "SUCCEEDED":
                    results = out.get("results") or []
                    if results:
                        img_url = str(results[0].get("url") or "")
                    break
                if st in ("FAILED", "CANCELED"):
                    raise RuntimeError(f"通义万相生成失败: {out.get('message') or st}")

            if not img_url:
                raise RuntimeError("通义万相生成超时")

            img_resp = await cli.get(img_url, follow_redirects=True, timeout=60.0)
            if img_resp.status_code >= 400:
                raise RuntimeError(f"下载图片失败 HTTP {img_resp.status_code}")

            filename = f"{job_id}.png"
            (self.out_dir / filename).write_bytes(img_resp.content)
            return filename

    async def _gen_openai(self, prompt: str, job_id: str, dcfg: dict[str, Any]) -> str:
        api_key = self._resolve_api_key()
        base = str(dcfg.get("base_url") or "https://api.openai.com/v1").strip().rstrip("/")
        model = str(dcfg.get("model") or "dall-e-3").strip()
        size = str(dcfg.get("size") or "1024x1024").replace("*", "x")

        url = base if base.endswith("/images/generations") else f"{base}/images/generations"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        body = {"model": model, "prompt": prompt, "n": 1, "size": size}

        async with httpx.AsyncClient(timeout=60.0) as cli:
            r = await cli.post(url, headers=headers, json=body)
            if r.status_code >= 400:
                raise RuntimeError(f"文生图失败 HTTP {r.status_code}: {r.text[:200]}")
            data = (r.json().get("data") or [])
            if not data:
                raise RuntimeError("文生图返回为空")
            item = data[0]
            if item.get("b64_json"):
                raw = base64.b64decode(item["b64_json"])
            elif item.get("url"):
                img_resp = await cli.get(item["url"], follow_redirects=True, timeout=60.0)
                raw = img_resp.content
            else:
                raise RuntimeError("文生图未返回图片 URL 或 base64")

        filename = f"{job_id}.png"
        (self.out_dir / filename).write_bytes(raw)
        return filename

    def status(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "queued": self.queue.qsize(),
            "current": self.current,
            "history": list(self.history)[:12],
        }

    async def _emit_state(self) -> None:
        if self.on_update:
            await self.on_update({"type": "draw", **self.status()})
