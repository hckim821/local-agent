import httpx
import json
import logging
import re
from typing import AsyncGenerator

# ── Thought-block filter ──────────────────────────────────────────────────────
# 일부 로컬 모델(Qwen3 등)이 내부 추론 과정을 특수 태그로 출력함.
# 스트리밍 도중 이 블록을 감지해 서버 로그에만 기록하고 클라이언트엔 전달하지 않음.

# thought 모드 진입 태그
_THINK_OPENS = ("<|channel>thought", "<think>")
# thought 모드 종료 태그
_THINK_CLOSES = ("</thought>", "</think>")
# <|channel>XXX 파서: channel 이름을 캡처 그룹으로 추출
_CHANNEL_RE = re.compile(r"<\|channel\|?>(\w*)\n?")
# thought 계열 채널 이름 (이 이름이면 thought 모드 유지)
_THOUGHT_CHANNELS = {"thought", "think", "thinking"}


def _longest_open_suffix(text: str) -> int:
    """text 끝부분이 어떤 OPEN 태그의 접두사와 겹치는 최대 길이를 반환."""
    best = 0
    for tag in _THINK_OPENS:
        for length in range(1, len(tag)):
            if text.endswith(tag[:length]):
                best = max(best, length)
    return best


def _strip_thought_blocks(text: str) -> str:
    """blocking_chat용: 완성된 텍스트에서 thought 블록을 일괄 제거."""
    # <think>...</think>
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    # <|channel>thought ... <|channel>answer (또는 끝)
    text = re.sub(
        r"<\|channel\|?>thought\b.*?(?=<\|channel\|?>\w|$)",
        "", text, flags=re.DOTALL,
    )
    # 남은 <|channel>answer 등 마커 제거
    text = _CHANNEL_RE.sub("", text)
    return text.strip()


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
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "chat_template_kwargs": {"thinking": False},
        }
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

        content = _strip_thought_blocks(content)
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
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "chat_template_kwargs": {"thinking": False},
        }
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
                                thought_acc += content
                                # ── thought 블록 내부: 닫는 태그 탐색 ────────
                                close_found = False
                                # 1) </thought>, </think> 명시적 닫기
                                for close in _THINK_CLOSES:
                                    pos = thought_acc.find(close)
                                    if pos != -1:
                                        logging.info("[LLM thought] %s", thought_acc[:pos].strip())
                                        remainder = thought_acc[pos + len(close):]
                                        thought_acc = ""
                                        in_thought = False
                                        close_found = True
                                        # 나머지에서 채널 마커 제거
                                        remainder = _CHANNEL_RE.sub("", remainder)
                                        pending += remainder
                                        break
                                # 2) <|channel>XXX — 채널 이름에 따라 분기
                                if not close_found:
                                    m = _CHANNEL_RE.search(thought_acc)
                                    if m:
                                        channel_name = m.group(1).lower()
                                        if channel_name in _THOUGHT_CHANNELS:
                                            # thought 계열 → thought 모드 유지, 기존 내용만 로그
                                            if m.start() > 0:
                                                logging.info("[LLM thought] %s", thought_acc[:m.start()].strip())
                                            thought_acc = thought_acc[m.end():]
                                        else:
                                            # answer 등 다른 채널 → thought 종료
                                            logging.info("[LLM thought] %s", thought_acc[:m.start()].strip())
                                            remainder = thought_acc[m.end():]
                                            thought_acc = ""
                                            in_thought = False
                                            pending += remainder
                            else:
                                pending += content

                            # ── thought 블록 밖: OPEN 태그 탐색 후 안전 구간 yield ──
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
