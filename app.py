"""DFYZB Open 独立桌面启动器入口（PyWebView 独立窗口 + 本地 FastAPI 引擎）。"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
import urllib.request

import uvicorn

from core.config import ROOT_DIR, load_config
from core.director import Director
from core.hub import Hub, HubLogHandler
from core.server import create_app


def setup_logging(hub: Hub) -> None:
    (ROOT_DIR / "logs").mkdir(exist_ok=True)
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    root.addHandler(sh)

    fh = logging.FileHandler(ROOT_DIR / "logs" / "dfyzb.log", encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)

    hh = HubLogHandler(hub)
    hh.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(hh)

    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def wait_server(url: str, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.15)
    return False


def main() -> None:
    cfg = load_config()
    host = str((cfg.get("server") or {}).get("host") or "127.0.0.1")
    port = int((cfg.get("server") or {}).get("port") or 18787)

    hub = Hub()
    setup_logging(hub)
    director = Director(hub)
    app = create_app(director, hub)

    server = uvicorn.Server(
        uvicorn.Config(app, host=host, port=port, log_level="warning", log_config=None)
    )
    t = threading.Thread(target=server.run, daemon=True)
    t.start()

    url = f"http://{host}:{port}"
    wait_server(f"{url}/api/status")

    try:
        import webview

        webview.create_window(
            title="鲶鱼大帝之大肥鱼一键开播助手",
            url=url,
            width=1220,
            height=800,
            min_size=(960, 660),
            background_color="#0b0f1d",
        )
        webview.start()
    except ImportError:
        import webbrowser

        logging.getLogger("dfyzb.app").warning(
            "未安装 pywebview，已回退为系统默认浏览器打开控制台：%s", url
        )
        webbrowser.open(url)
        try:
            while t.is_alive():
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
    finally:
        server.should_exit = True


if __name__ == "__main__":
    main()
