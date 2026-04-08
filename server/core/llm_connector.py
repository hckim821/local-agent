import httpx
import json
from typing import AsyncGenerator


class LLMConnector:
    def __init__(self, endpoint_url: str, api_key: str):
        self.endpoint_url = endpoint_url.rstrip("/")
        self.api_key = api_key

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def chat(
        self,
        messages: list,
        model: str,
        tools: list | None = None,
        stream: bool = False,
    ):
        payload = {
            "model": model,
            "messages": messages,
            "stream": stream,
        }
        if tools:
            payload["tools"] = tools

        base = self.endpoint_url.rstrip("/")
        if base.endswith("/v1"):
            url = f"{base}/chat/completions"
        else:
            url = f"{base}/v1/chat/completions"

        if stream:
            return self._stream_chat(url, payload)
        else:
            return await self._blocking_chat(url, payload)

    async def _blocking_chat(self, url: str, payload: dict) -> dict:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(url, headers=self._headers(), json=payload)
            response.raise_for_status()
            data = response.json()

        choice = data["choices"][0]
        message = choice["message"]
        content = message.get("content") or ""
        tool_calls = message.get("tool_calls") or []

        parsed_tool_calls = []
        for tc in tool_calls:
            try:
                args = json.loads(tc["function"]["arguments"])
            except (json.JSONDecodeError, KeyError):
                args = {}
            parsed_tool_calls.append({
                "id": tc.get("id", ""),
                "name": tc["function"]["name"],
                "arguments": args,
            })

        return {"content": content, "tool_calls": parsed_tool_calls}

    async def _stream_chat(self, url: str, payload: dict) -> AsyncGenerator[dict, None]:
        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream("POST", url, headers=self._headers(), json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    raw = line[6:]
                    if raw.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(raw)
                        choice = chunk["choices"][0]
                        delta = choice.get("delta", {})
                        content = delta.get("content")
                        if content:
                            yield {"content": content, "tool_calls": []}
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
