"""FastAPI 本地控制与 OBS 舞台服务。"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import ROOT_DIR
from .director import Director
from .events import Event, clean_text
from .hub import Hub

log = logging.getLogger("dfyzb.server")


def create_app(director: Director, hub: Hub) -> FastAPI:
    app = FastAPI(title="鲶鱼大帝之大肥鱼一键开播助手")

    (ROOT_DIR / "data" / "draws").mkdir(parents=True, exist_ok=True)
    app.mount("/stage", StaticFiles(directory=str(ROOT_DIR / "stage"), html=True), name="stage")
    app.mount("/ui", StaticFiles(directory=str(ROOT_DIR / "ui"), html=True), name="ui")
    app.mount("/draws", StaticFiles(directory=str(ROOT_DIR / "data" / "draws")), name="draws")

    @app.get("/")
    async def root_ui():
        return FileResponse(ROOT_DIR / "ui" / "index.html")

    # -------------------- 配置与状态 --------------------

    @app.get("/api/config")
    async def get_config():
        return {"ok": True, "config": director.cfg}

    @app.post("/api/config")
    async def post_config(req: Request):
        body = await req.json()
        cfg = director.apply_config(body)
        return {"ok": True, "config": cfg}

    @app.get("/api/status")
    async def get_status():
        return {"ok": True, **director.status()}

    @app.get("/api/logs")
    async def get_logs():
        return {"ok": True, "logs": list(hub.logs)}

    # -------------------- 一键开播 & 独立模块控制 --------------------

    @app.post("/api/live/start")
    async def api_live_start():
        return await director.start_live()

    @app.post("/api/live/stop")
    async def api_live_stop():
        return await director.stop_live()

    @app.post("/api/feature/{name}")
    async def api_feature_toggle(name: str, req: Request):
        body = await req.json()
        enabled = bool(body.get("enabled", False))
        return await director.set_feature(name, enabled)

    # -------------------- 本地曲库控制 --------------------

    @app.post("/api/music/scan")
    async def api_music_scan():
        cnt = director.music.scan_library()
        return {"ok": True, "count": cnt, "message": f"已扫描到本地歌曲 {cnt} 首"}

    @app.post("/api/music/skip")
    async def api_music_skip():
        msg = await director.music.skip()
        return {"ok": True, "message": msg}

    # -------------------- 测试与调试接口 --------------------

    @app.post("/api/test/llm")
    async def api_test_llm():
        return await director.llm.test_connection()

    @app.post("/api/test/tts")
    async def api_test_tts(req: Request):
        body = await req.json()
        text = clean_text(body.get("text") or "你好呀，欢迎来到直播间！语音合成测试成功！")
        try:
            await director.say(text)
            return {"ok": True, "message": "语音播放完成"}
        except Exception as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)

    @app.post("/api/test/event")
    async def api_test_event(req: Request):
        body = await req.json()
        kind = str(body.get("kind") or "comment")
        ev = Event(
            kind=kind,
            user=str(body.get("user") or "测试观众"),
            text=clean_text(body.get("text") or ""),
            gift=str(body.get("gift") or "小心心"),
            count=max(1, int(body.get("count") or 1)),
            price=float(body.get("price") or 0.0),
            platform="test",
        )
        await director.on_event(ev)
        return {"ok": True, "event": ev.to_dict()}

    @app.post("/api/test/draw")
    async def api_test_draw(req: Request):
        body = await req.json()
        prompt = clean_text(body.get("prompt") or "一只戴着耳机的赛博朋克小橘猫")
        if not director.draw.running:
            await director.draw.start()
        ok, msg = await director.draw.enqueue(prompt, user="测试观众", force=True)
        return {"ok": ok, "message": msg}

    @app.post("/api/memory/clear")
    async def api_clear_memory():
        director.llm.clear_memory()
        return {"ok": True, "message": "已清空对话记忆"}

    @app.post("/api/gift/reset")
    async def api_reset_gifts():
        director.gifts.reset()
        await hub.broadcast({"type": "gift_reset", "board": director.gifts.snapshot()})
        return {"ok": True, "message": "已重置本场礼物榜"}

    # -------------------- OBS WebSocket --------------------

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        await ws.accept()
        hub.clients.add(ws)
        try:
            for item in hub.snapshot_for_client():
                await ws.send_json(item)
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            hub.clients.discard(ws)

    return app
