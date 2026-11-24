"""皮套接口：VTube Studio Public API（ws://127.0.0.1:8001）异步客户端。

用途：
- 连接本地 VTube Studio（用户在 B站自行获取开源皮套并加载到 VTS 中）；
- 主播 TTS 开口说话时实时注入 MouthOpen 参数驱动口型，说完自动闭嘴；
- 首次连接会在 VTube Studio 弹窗请求授权，授权后自动缓存 token 至 data/vts_token.json。
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from pathlib import Path
from typing import Any

from .config import ROOT_DIR

log = logging.getLogger("dfyzb.vts")

API_NAME = "VTubeStudioPublicAPI"
API_VERSION = "1.0"
PLUGIN_NAME = "DFYZB-Open"
PLUGIN_DEVELOPER = "DFYZB-Open"


class VTSClient:
    def __init__(self, cfg: dict[str, Any]) -> None:
        self.cfg = cfg
        self.token_path = ROOT_DIR / "data" / "vts_token.json"
        self.running = False
        self.connected = False
        self.last_error = ""
        self._ws = None
        self._req_id = 0
        self._speaking = False
        self._task: asyncio.Task | None = None

    def update_config(self, cfg: dict[str, Any]) -> None:
        self.cfg = cfg

    def _vcfg(self) -> dict[str, Any]:
        return self.cfg.get("vts") or {}

    def _load_token(self) -> str:
        try:
            if self.token_path.exists():
                return str(json.loads(self.token_path.read_text(encoding="utf-8")).get("token") or "")
        except Exception:
            pass
        return ""

    def _save_token(self, token: str) -> None:
        try:
            self.token_path.parent.mkdir(parents=True, exist_ok=True)
            self.token_path.write_text(
                json.dumps({"token": token, "saved_at": int(time.time())}, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass

    async def _call(self, msg_type: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        self._req_id += 1
        payload = {
            "apiName": API_NAME,
            "apiVersion": API_VERSION,
            "requestID": f"dfyzb-{self._req_id}",
            "messageType": msg_type,
            "data": data or {},
        }
        await self._ws.send(json.dumps(payload))
        raw = await asyncio.wait_for(self._ws.recv(), timeout=15.0)
        return json.loads(raw)

    async def start(self) -> tuple[bool, str]:
        if self.running:
            return True, "VTube Studio 皮套接口已连接"
        self.running = True
        self.last_error = ""
        self._task = asyncio.create_task(self._loop())
        await asyncio.sleep(0.4)
        if self.last_error:
            return False, self.last_error
        return True, "正在连接 VTube Studio 皮套接口（首次请在 VTS 窗口点允许）"

    async def stop(self) -> None:
        self.running = False
        self.connected = False
        self._speaking = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await self._close()

    async def _close(self) -> None:
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

    def set_speaking(self, speaking: bool) -> None:
        self._speaking = bool(speaking)

    async def _authenticate(self) -> bool:
        token = self._load_token()
        if token:
            r = await self._call("AuthenticationRequest", {
                "pluginName": PLUGIN_NAME,
                "pluginDeveloper": PLUGIN_DEVELOPER,
                "authenticationToken": token,
            })
            if (r.get("data") or {}).get("authenticated"):
                return True

        # 申请新 token（VTS 会弹窗让用户点允许）
        r = await self._call("AuthenticationTokenRequest", {
            "pluginName": PLUGIN_NAME,
            "pluginDeveloper": PLUGIN_DEVELOPER,
        })
        token = str((r.get("data") or {}).get("authenticationToken") or "")
        if not token:
            self.last_error = "VTube Studio 拒绝或未确认插件授权"
            return False
        self._save_token(token)

        r2 = await self._call("AuthenticationRequest", {
            "pluginName": PLUGIN_NAME,
            "pluginDeveloper": PLUGIN_DEVELOPER,
            "authenticationToken": token,
        })
        if not (r2.get("data") or {}).get("authenticated"):
            self.last_error = "VTube Studio Token 鉴权失败"
            return False
        return True

    async def _inject_mouth(self, value: float, param_id: str) -> None:
        if not self._ws:
            return
        await self._call("InjectParameterDataRequest", {
            "faceFound": False,
            "mode": "set",
            "parameterValues": [{"id": param_id, "value": round(max(0.0, min(1.0, value)), 3)}],
        })

    async def _loop(self) -> None:
        import websockets

        vcfg = self._vcfg()
        host = str(vcfg.get("host") or "127.0.0.1").strip()
        port = int(vcfg.get("port") or 8001)
        mouth_param = str(vcfg.get("mouth_param") or "MouthOpen").strip()
        uri = f"ws://{host}:{port}"

        try:
            async with websockets.connect(uri, open_timeout=5.0) as ws:
                self._ws = ws
                if not await self._authenticate():
                    log.warning("VTS 鉴权失败: %s", self.last_error)
                    self.running = False
                    return
                self.connected = True
                log.info("VTube Studio 皮套接口已连接：%s", uri)
                t0 = time.monotonic()
                last_zero_sent = True

                while self.running:
                    if self._speaking:
                        dt = time.monotonic() - t0
                        # 平滑口型包络（0.25 ~ 0.92 之间自然张合）
                        val = 0.55 + 0.35 * math.sin(dt * 16.0) * math.cos(dt * 5.3)
                        await self._inject_mouth(val, mouth_param)
                        last_zero_sent = False
                        await asyncio.sleep(0.06)
                    else:
                        if not last_zero_sent:
                            await self._inject_mouth(0.0, mouth_param)
                            last_zero_sent = True
                        await asyncio.sleep(0.15)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.last_error = f"无法连接 VTube Studio ({uri})，请确认已开启 VTS API：{exc}"
            log.warning("VTS 连接异常: %s", self.last_error)
        finally:
            self.connected = False
            self.running = False
            self._ws = None

    def status(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "connected": self.connected,
            "error": self.last_error,
        }
