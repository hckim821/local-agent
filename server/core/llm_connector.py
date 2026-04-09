import httpx
import json
import logging
import re
from typing import AsyncGenerator

# ── Thought-block filter ──────────────────────────────────────────────────────
# 일부 로컬 모델(Qwen3 등)이 내부 추론 과정을 특수 태그로 출력함.
# 스트리밍 도중 이 블록을 감지해 서버 로그에만 기록하고 클라이언트엔 전달하지 않음.
_THINK_OPENS = ("<|channel>thought", "<think>")
_THINK_CLOSES = ("</thought>", "</think>")
# <|channel>answer 등 다음 채널 마커: <|channel> 뒤에 오는 단어+개행까지 통째로 제거
_NEXT_CHANNEL_RE = re.compile(r"<\|channel>[^\n<]*\n?")


def _longest_open_suffix(text: str) -> int:
    """text 끝부분이 어떤 OPEN 태그의 접두사와 겹치는 최대 길이를 반환."""
    best = 0
    for tag in _THINK_OPENS:
        for length in range(1, len(tag)):
            if text.endswith(tag[:length]):
                best = max(best, length)
    return best


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

        # ── Thought-block filter state ────────────────────────────────────────
        pending = ""       # 아직 yield하지 않은 일반 content (태그 경계 감지용 버퍼)
        in_thought = False # thought 블록 내부 여부
        thought_acc = ""   # thought 블록 누적 (로그용)

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
                            if in_thought:
                                # thought 블록 누적 → 닫는 태그 탐색
                                thought_acc += content
                                close_found = False
                                for close in _THINK_CLOSES:
                                    pos = thought_acc.find(close)
                                    if pos != -1:
                                        logging.info(
                                            "[LLM thought] %s",
                                            thought_acc[:pos].strip(),
                                        )
                                        remainder = thought_acc[pos + len(close):]
                                        thought_acc = ""
                                        in_thought = False
                                        close_found = True
                                        # 닫힌 뒤 남은 텍스트에 <|channel>answer 같은
                                        # 채널 마커가 있으면 제거
                                        remainder = _NEXT_CHANNEL_RE.sub("", remainder)
                                        pending += remainder
                                        break
                                # <|channel>XXX 형태의 다음 채널 마커도 닫기로 처리
                                if not close_found:
                                    m = _NEXT_CHANNEL_RE.search(thought_acc)
                                    if m and not thought_acc.startswith(m.group()):
                                        # 마커 앞까지가 thought 내용
                                        pos = m.start()
                                        logging.info(
                                            "[LLM thought] %s",
                                            thought_acc[:pos].strip(),
                                        )
                                        remainder = thought_acc[m.end():]
                                        thought_acc = ""
                                        in_thought = False
                                        pending += remainder
                            else:
                                pending += content

                            # thought 블록 밖: pending에서 OPEN 태그 탐색 후 안전 구간 yield
                            if not in_thought:
                                for open_tag in _THINK_OPENS:
                                    op = pending.find(open_tag)
                                    if op != -1:
                                        if op > 0:
                                            yield {"type": "content", "value": pending[:op]}
                                        in_thought = True
                                        thought_acc = pending[op + len(open_tag):]
                                        pending = ""
                                        break
                                else:
                                    # OPEN 태그의 앞부분이 pending 끝에 걸칠 수 있으므로
                                    # 그 길이만큼 버퍼에 남기고 나머지만 yield
                                    hold = _longest_open_suffix(pending)
                                    safe = len(pending) - hold
                                    if safe > 0:
                                        yield {"type": "content", "value": pending[:safe]}
                                        pending = pending[safe:]

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

        # 스트림 종료 후 남은 버퍼 처리
        if in_thought and thought_acc:
            logging.info("[LLM thought] %s", thought_acc.strip())
        if pending and not in_thought:
            yield {"type": "content", "value": pending}

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
