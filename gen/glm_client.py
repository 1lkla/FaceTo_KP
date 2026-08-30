#!/usr/bin/env python3
"""GLM 异步客户端：同时支持 anthropic / openai 两种协议（按 GLM_PROTOCOL 切换）。

环境变量（从项目根 .env 读取）：
  GLM_BASE_URL / GLM_API_KEY / GLM_MODEL / GLM_PROTOCOL(anthropic|openai)
  GEN_CONCURRENCY 并发上限，默认 8
"""
import asyncio
import os
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_env(path: Path = PROJECT_ROOT / ".env") -> dict:
    env = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


class GLMClient:
    MAX_RETRIES = 5
    TIMEOUT = 120

    def __init__(self):
        env = load_env()
        self.base_url = env.get("GLM_BASE_URL", "").rstrip("/")
        self.api_key = env.get("GLM_API_KEY", "")
        self.model = env.get("GLM_MODEL", "GLM-5.3-Flash")
        self.protocol = env.get("GLM_PROTOCOL", "anthropic").lower()
        if self.protocol not in ("anthropic", "openai"):
            raise ValueError(f"不支持的 GLM_PROTOCOL: {self.protocol}")
        if not self.base_url or not self.api_key:
            raise RuntimeError("缺少 GLM_BASE_URL 或 GLM_API_KEY")
        concurrency = int(os.environ.get("GEN_CONCURRENCY", "8"))
        self.semaphore = asyncio.Semaphore(concurrency)
        self.total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    def _request(self, messages, max_tokens):
        if self.protocol == "anthropic":
            url = f"{self.base_url}/v1/messages"
            headers = {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }
            body = {"model": self.model, "max_tokens": max_tokens, "messages": messages}
        else:
            url = f"{self.base_url}/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "content-type": "application/json",
            }
            body = {"model": self.model, "max_tokens": max_tokens, "messages": messages}
        return url, headers, body

    @staticmethod
    def _parse(protocol, data):
        """返回 (text, usage_dict)。"""
        if protocol == "anthropic":
            text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
            u = data.get("usage", {})
            usage = {
                "prompt_tokens": u.get("input_tokens", 0),
                "completion_tokens": u.get("output_tokens", 0),
                "total_tokens": u.get("input_tokens", 0) + u.get("output_tokens", 0),
            }
        else:
            text = data["choices"][0]["message"]["content"]
            u = data.get("usage", {})
            usage = {
                "prompt_tokens": u.get("prompt_tokens", 0),
                "completion_tokens": u.get("completion_tokens", 0),
                "total_tokens": u.get("total_tokens", 0),
            }
        return text, usage

    async def chat(self, messages, max_tokens=4096):
        """带并发控制与 429/5xx 指数退避重试。返回 (text, usage)。"""
        url, headers, body = self._request(messages, max_tokens)
        async with self.semaphore:
            async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
                for attempt in range(self.MAX_RETRIES):
                    try:
                        resp = await client.post(url, headers=headers, json=body)
                        if resp.status_code == 429 or resp.status_code >= 500:
                            wait = 2 ** attempt
                            print(f"  [retry] HTTP {resp.status_code}, {wait}s 后重试 ({attempt + 1}/{self.MAX_RETRIES})")
                            await asyncio.sleep(wait)
                            continue
                        resp.raise_for_status()
                        text, usage = self._parse(self.protocol, resp.json())
                        for k in self.total_usage:
                            self.total_usage[k] += usage.get(k, 0)
                        return text, usage
                    except (httpx.TimeoutException, httpx.TransportError) as e:
                        wait = 2 ** attempt
                        print(f"  [retry] {type(e).__name__}: {e}, {wait}s 后重试 ({attempt + 1}/{self.MAX_RETRIES})")
                        await asyncio.sleep(wait)
                raise RuntimeError(f"请求失败，已重试 {self.MAX_RETRIES} 次: {url}")
