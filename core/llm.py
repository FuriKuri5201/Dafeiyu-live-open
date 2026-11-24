"""通用 OpenAI 兼容大语言模型客户端（支持 DeepSeek / 通义千问 / OpenAI / Ollama 等任意模型）。"""
from __future__ import annotations

import logging
from collections import deque
from typing import Any

import httpx

log = logging.getLogger("dfyzb.llm")


class LLMClient:
    def __init__(self, cfg: dict[str, Any]) -> None:
        self.cfg = cfg
        self.history: deque[dict[str, str]] = deque(maxlen=40)

    def update_config(self, cfg: dict[str, Any]) -> None:
        self.cfg = cfg

    def clear_memory(self) -> None:
        self.history.clear()

    def _build_endpoint(self, base_url: str) -> str:
        base = (base_url or "https://api.deepseek.com/v1").strip().rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"

    async def chat(
        self,
        user_text: str,
        user_name: str = "观众",
        extra_context: str = "",
        remember: bool = True,
    ) -> str:
        llm_cfg = self.cfg.get("llm") or {}
        streamer_cfg = self.cfg.get("streamer") or {}

        api_key = str(llm_cfg.get("api_key") or "").strip()
        base_url = str(llm_cfg.get("base_url") or "https://api.deepseek.com/v1").strip()
        model = str(llm_cfg.get("model") or "deepseek-chat").strip()
        temperature = float(llm_cfg.get("temperature", 0.85))
        max_tokens = int(llm_cfg.get("max_tokens", 120))
        mem_enable = bool(llm_cfg.get("memory_enable", True))
        mem_turns = max(0, int(llm_cfg.get("memory_turns", 12)))

        if not api_key and "127.0.0.1" not in base_url and "localhost" not in base_url:
            raise RuntimeError("未填写对话模型 API Key，请先在启动器中填写。")

        name = str(streamer_cfg.get("name") or "大肥鱼AI").strip()
        persona = str(streamer_cfg.get("persona") or "你是一位幽默风趣的直播间 AI 主播。").strip()
        system_prompt = f"你的名字是「{name}」。\n{persona}"
        if extra_context:
            system_prompt += f"\n当前直播间信息：{extra_context}"

        messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
        if mem_enable and mem_turns > 0:
            messages.extend(list(self.history)[-(mem_turns * 2):])

        prompt = f"观众「{user_name}」说：{user_text}" if user_name else user_text
        messages.append({"role": "user", "content": prompt})

        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        url = self._build_endpoint(base_url)
        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code >= 400:
                raise RuntimeError(f"LLM 请求失败 HTTP {resp.status_code}: {resp.text[:240]}")
            data = resp.json()

        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("LLM 返回内容为空")
        reply = str((choices[0].get("message") or {}).get("content") or "").strip()
        if not reply:
            raise RuntimeError("LLM 回复为空文本")

        if remember and mem_enable:
            self.history.append({"role": "user", "content": prompt})
            self.history.append({"role": "assistant", "content": reply})

        return reply

    async def test_connection(self) -> dict[str, Any]:
        try:
            reply = await self.chat("你好，用一句话自我介绍一下", user_name="测试", remember=False)
            return {"ok": True, "reply": reply}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
