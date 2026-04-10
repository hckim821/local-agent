import json
import logging
from typing import AsyncGenerator
from .llm_connector import LLMConnector, _strip_thought_blocks


class Orchestrator:
    def __init__(self):
        self._context: list[dict] = []

    def reset(self):
        self._context = []

    async def process(
        self,
        user_message: str,
        endpoint_url: str,
        api_key: str,
        model: str,
        skill_registry,
        stream: bool = False,
        image: str | None = None,
    ):
        if image:
            content: list | str = [
                {"type": "text", "text": user_message or "이 이미지를 분석해줘."},
                {"type": "image_url", "image_url": {"url": image}},
            ]
            logging.info("[Orchestrator] Multimodal message (image attached)")
        else:
            content = user_message

        self._context.append({"role": "user", "content": content})
        connector = LLMConnector(endpoint_url, api_key)
        # Don't pass tools for vision requests — most local models don't support both
        tools = None if image else (skill_registry.to_tools() or None)

        if stream:
            return self._stream_loop(connector, model, tools, skill_registry)
        else:
            return await self._blocking_loop(connector, model, tools, skill_registry)

    # ── Non-streaming path (used after tool execution follow-ups) ────────────

    async def _blocking_loop(
        self, connector: LLMConnector, model: str, tools, skill_registry
    ) -> str:
        for _ in range(10):
            result = await connector.blocking_chat(
                messages=self._context, model=model, tools=tools
            )
            content = result["content"]
            tool_calls = result["tool_calls"]

            if not tool_calls:
                self._context.append({"role": "assistant", "content": content})
                return content

            self._context.append(self._build_assistant_msg(content, tool_calls))
            await self._execute_tools(tool_calls, skill_registry)

        return "최대 반복 횟수에 도달했습니다."

    # ── Streaming path ────────────────────────────────────────────────────────

    async def _stream_loop(
        self, connector: LLMConnector, model: str, tools, skill_registry
    ) -> AsyncGenerator[str, None]:
        """
        Streams LLM tokens to the client as they arrive.
        Tool calls are executed and the loop continues until the LLM returns no more tool calls.
        """
        for _ in range(10):
            accumulated_content = ""
            tool_calls = []

            # ── LLM에 보내는 전체 context 디버그 출력 ──────────────────────
            logging.info("=" * 80)
            logging.info("[LLM REQUEST] model=%s, tools=%d개", model, len(tools) if tools else 0)
            for i, msg in enumerate(self._context):
                role = msg.get("role", "?")
                content = msg.get("content", "")
                # content가 리스트(멀티모달)인 경우 요약
                if isinstance(content, list):
                    parts_summary = []
                    for part in content:
                        if part.get("type") == "text":
                            text_val = part.get("text", "")
                            parts_summary.append(f"text({len(text_val)}자): {text_val[:200]}")
                        elif part.get("type") == "image_url":
                            url = part.get("image_url", {}).get("url", "")
                            parts_summary.append(f"image({len(url)}bytes)")
                        else:
                            parts_summary.append(str(part)[:100])
                    content_display = " | ".join(parts_summary)
                elif isinstance(content, str):
                    content_display = content[:300]
                else:
                    content_display = str(content)[:300]
                # tool_calls 요약
                tc_info = ""
                if msg.get("tool_calls"):
                    tc_names = [tc["function"]["name"] for tc in msg["tool_calls"]]
                    tc_info = f" → tool_calls: {tc_names}"
                # tool_call_id 표시
                tcid = f" [tool_call_id={msg['tool_call_id']}]" if "tool_call_id" in msg else ""
                logging.info(
                    "[CTX %02d] role=%-10s%s%s | %s",
                    i, role, tcid, tc_info, content_display,
                )
            if tools:
                tool_names = [t["function"]["name"] for t in tools]
                logging.info("[TOOLS] %s", tool_names)
            logging.info("=" * 80)

            async for event in connector.stream_tokens(
                messages=self._context, model=model, tools=tools
            ):
                if event["type"] == "content":
                    token = event["value"]
                    accumulated_content += token
                    yield token
                elif event["type"] == "tool_calls":
                    tool_calls = event["value"]

            # context에 thought 잔해가 쌓이면 모델이 이를 보고 또 thinking → 무한루프
            clean_content = _strip_thought_blocks(accumulated_content)
            self._context.append(
                self._build_assistant_msg(clean_content, tool_calls)
            )

            if not tool_calls:
                return

            for tc in tool_calls:
                yield f"\n\n⚙ 스킬 실행 중: **{tc['name']}**...\n"
                logging.info(f"[Skill] Running {tc['name']} with {tc['arguments']}")

                skill = skill_registry.get(tc["name"])
                if skill is None:
                    tool_result = {"error": f"Skill '{tc['name']}' not found"}
                else:
                    try:
                        tool_result = await skill.run(**tc["arguments"])
                    except Exception as e:
                        tool_result = {"error": str(e)}

                # 이미지 수집: 단일(image_base64) 또는 다중(images_base64) 모두 지원
                images: list[str] = []
                single = tool_result.pop("image_base64", None)
                if single:
                    images.append(single)
                multi = tool_result.pop("images_base64", None)
                if multi:
                    images.extend(multi)

                # 채팅창에 이미지 표시
                labels = ["클릭 전", "클릭 후"] if len(images) >= 2 else ["스크린샷"] * len(images)
                for label, img_b64 in zip(labels, images):
                    yield f"\n**[{label}]**\n![{label}](data:image/jpeg;base64,{img_b64})\n"

                logging.info(f"[Skill] Result: {tool_result}")

                # 마지막 이미지를 LLM context에 포함 (분석용)
                if images:
                    content_parts: list = [
                        {"type": "text", "text": json.dumps(tool_result, ensure_ascii=False)}
                    ]
                    for img_b64 in images:
                        content_parts.append({
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"},
                        })
                    self._context.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": content_parts,
                    })
                else:
                    self._context.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": json.dumps(tool_result, ensure_ascii=False),
                    })

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _build_assistant_msg(content: str, tool_calls: list) -> dict:
        msg: dict = {"role": "assistant", "content": content}
        if tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": json.dumps(tc["arguments"]),
                    },
                }
                for tc in tool_calls
            ]
        return msg

    async def _execute_tools(self, tool_calls: list, skill_registry) -> None:
        for tc in tool_calls:
            skill = skill_registry.get(tc["name"])
            if skill is None:
                result = {"error": f"Skill '{tc['name']}' not found"}
            else:
                try:
                    result = await skill.run(**tc["arguments"])
                except Exception as e:
                    result = {"error": str(e)}

            # 이미지 수집: 단일(image_base64) 또는 다중(images_base64) 모두 지원
            images: list[str] = []
            single = result.pop("image_base64", None)
            if single:
                images.append(single)
            multi = result.pop("images_base64", None)
            if multi:
                images.extend(multi)

            if images:
                content_parts: list = [
                    {"type": "text", "text": json.dumps(result, ensure_ascii=False)}
                ]
                for img_b64 in images:
                    content_parts.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"},
                    })
                self._context.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": content_parts,
                })
            else:
                self._context.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": json.dumps(result, ensure_ascii=False),
                })
