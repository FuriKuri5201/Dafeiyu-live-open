"""无界面命令行启动入口（适合调试、服务器部署或二次开发）。"""
from __future__ import annotations

import logging
import sys

import uvicorn

from core.config import ROOT_DIR, load_config
from core.director import Director
from core.hub import Hub, HubLogHandler
from core.server import create_app


def main() -> None:
    cfg = load_config()
    host = str((cfg.get("server") or {}).get("host") or "127.0.0.1")
    port = int((cfg.get("server") or {}).get("port") or 18787)

    hub = Hub()
    (ROOT_DIR / "logs").mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            HubLogHandler(hub),
        ],
    )
    director = Director(hub)
    app = create_app(director, hub)
    print(f"[鲶鱼大帝之大肥鱼一键开播助手] 控制台已启动：http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
