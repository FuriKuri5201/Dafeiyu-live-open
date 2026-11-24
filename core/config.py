"""配置管理：默认模板合并、原子读写、自动探测本机浏览器。"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent
EXAMPLE_CONFIG_PATH = ROOT_DIR / "config.example.json"
CONFIG_PATH = ROOT_DIR / "config.json"


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def default_config() -> dict[str, Any]:
    if EXAMPLE_CONFIG_PATH.exists():
        return json.loads(EXAMPLE_CONFIG_PATH.read_text(encoding="utf-8"))
    return {
        "server": {"host": "127.0.0.1", "port": 18787},
        "streamer": {"name": "大肥鱼AI", "persona": "你是一位幽默风趣的直播间 AI 主播。"},
        "features": {
            "douyin": False,
            "bilibili": False,
            "chat": True,
            "gift": True,
            "music": True,
            "draw": False,
            "vts": False,
            "obs_stage": True,
        },
        "llm": {
            "provider": "openai_compatible",
            "base_url": "https://api.deepseek.com/v1",
            "api_key": "",
            "model": "deepseek-chat",
            "temperature": 0.85,
            "max_tokens": 120,
            "memory_enable": True,
            "memory_turns": 12,
        },
        "tts": {
            "provider": "edge",
            "api_key": "",
            "base_url": "",
            "model": "",
            "voice": "zh-CN-XiaoxiaoNeural",
            "rate": "+5%",
            "volume": "+0%",
            "pitch": "+0Hz",
        },
        "collectors": {
            "browser_path": "",
            "douyin": {"room_url": "", "headless": False, "profile_dir": "profiles/douyin"},
            "bilibili": {"room_id": "", "headless": False, "profile_dir": "profiles/bilibili"},
        },
        "gift": {
            "thank_enable": True,
            "thank_template": "谢谢{user}送的{count}个{gift}，太爱你啦！",
            "use_llm_thank": False,
        },
        "music": {
            "dirs": ["music"],
            "volume": 0.45,
            "duck_volume": 0.14,
            "auto_next": True,
            "trigger_prefixes": ["点歌", "来首", "放首", "播放"],
            "skip_keywords": ["切歌", "下一首"],
        },
        "draw": {
            "provider": "wanx",
            "base_url": "https://dashscope.aliyuncs.com/api/v1",
            "api_key": "",
            "reuse_tts_key": True,
            "model": "wanx2.1-t2i-turbo",
            "size": "1024*1024",
            "style_prompt": "二次元插画风格，精致细节，明快配色",
            "trigger_prefixes": ["画", "画一个", "画一只", "帮我画"],
            "cooldown_sec": 15,
        },
    }


def load_config() -> dict[str, Any]:
    defaults = default_config()
    if not CONFIG_PATH.exists():
        save_config(defaults)
        return defaults
    try:
        user_cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return _deep_merge(defaults, user_cfg)
    except Exception:
        return defaults


def save_config(cfg: dict[str, Any]) -> dict[str, Any]:
    merged = _deep_merge(default_config(), cfg)
    tmp = CONFIG_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(CONFIG_PATH)
    return merged


def detect_browser_executable(configured: str = "") -> str | None:
    """自动探测本机 Chrome 或 Windows 自带 Microsoft Edge，省去下载数百 MB Chromium。"""
    if configured:
        p = Path(configured)
        if p.exists():
            return str(p)

    candidates = [
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        Path(os.environ.get("LOCALAPPDATA", "")) / r"Google\Chrome\Application\chrome.exe",
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    ]
    for path in candidates:
        if path.is_file():
            return str(path)
    return None
