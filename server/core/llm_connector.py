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

    def _url(self) -> str:
        base = self.endpoint_url.rstrip("/")
        if base.endswith("/v1"):
            return f"{base}/chat/completions"
        return f"{base}/v1/chat/completions"

    async def blocking_chat(
        self,
        messages: list,
        model: str,
        tools: list | None = None,
    ) -> dict:
        """Non-streaming call. Returns {"content": str, "tool_calls": [...]}."""
        payload = {"model": model, "messages": messages, "stream": False}
        if tools:
            payload["tools"] = tools

        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(self._url(), headers=self._headers(), json=payload)
            response.raise_for_status()
            data = response.json()

        choice = data["choices"][0]
        message = choice["message"]
        content = message.get("content") or ""
        tool_calls = message.get("tool_calls") or []

        parsed = []
        for tc in tool_calls:
            try:
                args = json.loads(tc["function"]["arguments"])
            except (json.JSONDecodeError, KeyError):
                args = {}
            parsed.append({
                "id": tc.get("id", ""),
                "name": tc["function"]["name"],
                "arguments": args,
            })

        return {"content": content, "tool_calls": parsed}

    async def stream_tokens(
        self,
        messages: list,
        model: str,
        tools: list | None = None,
    ) -> AsyncGenerator[dict, None]:
        """
        True streaming call. Yields dicts:
          {"type": "content", "value": str}   — one token from the LLM
          {"type": "tool_calls", "value": [...]} — accumulated tool calls at end of stream
        """
        payload = {"model": model, "messages": messages, "stream": True}
        if tools:
            payload["tools"] = tools

        # Accumulate tool call deltas across chunks
        # key: index, value: {"id", "name", "arguments_str"}
        tc_acc: dict[int, dict] = {}

        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream(
                "POST", self._url(), headers=self._headers(), json=payload
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    raw = line[6:].strip()
                    if raw == "[DONE]":
                        break
                    try:
                        chunk = json.loads(raw)
                        choice = chunk["choices"][0]
                        delta = choice.get("delta", {})

                        # --- content token ---
                        content = delta.get("content")
                        if content:
                            yield {"type": "content", "value": content}

                        # --- tool call delta ---
                        for tc_delta in delta.get("tool_calls", []):
                            idx = tc_delta.get("index", 0)
                            if idx not in tc_acc:
                                tc_acc[idx] = {"id": "", "name": "", "arguments_str": ""}
                            if tc_delta.get("id"):
                                tc_acc[idx]["id"] = tc_delta["id"]
                            fn = tc_delta.get("function", {})
                            if fn.get("name"):
                                tc_acc[idx]["name"] = fn["name"]
                            if fn.get("arguments"):
                                tc_acc[idx]["arguments_str"] += fn["arguments"]

                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue

        # Emit accumulated tool calls once at the end
        if tc_acc:
            parsed = []
            for idx in sorted(tc_acc.keys()):
                tc = tc_acc[idx]
                try:
                    args = json.loads(tc["arguments_str"]) if tc["arguments_str"] else {}
                except json.JSONDecodeError:
                    args = {}
                parsed.append({"id": tc["id"], "name": tc["name"], "arguments": args})
            yield {"type": "tool_calls", "value": parsed}
