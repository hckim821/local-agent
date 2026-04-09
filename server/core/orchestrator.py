import json
import logging
from typing import AsyncGenerator
from .llm_connector import LLMConnector


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
            # Build OpenAI vision multimodal content
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

            async for event in connector.stream_tokens(
                messages=self._context, model=model, tools=tools
            ):
                if event["type"] == "content":
                    token = event["value"]
                    accumulated_content += token
                    yield token
                elif event["type"] == "tool_calls":
                    tool_calls = event["value"]

            self._context.append(
                self._build_assistant_msg(accumulated_content, tool_calls)
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

                # 스크린샷이면 이미지를 채팅창에 표시
                b64 = tool_result.pop("image_base64", None)
                if b64:
                    yield f"\n![스크린샷](data:image/png;base64,{b64})\n"

                logging.info(f"[Skill] Result: {tool_result}")

                # 이미지가 있으면 멀티모달 content로 context에 포함 → LLM이 이미지 분석 가능
                if b64:
                    self._context.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": [
                            {"type": "text", "text": json.dumps(tool_result, ensure_ascii=False)},
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                        ],
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

            # 이미지가 있으면 멀티모달 content로 context에 포함 → LLM이 이미지 분석 가능
            b64 = result.pop("image_base64", None)
            if b64:
                self._context.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": [
                        {"type": "text", "text": json.dumps(result, ensure_ascii=False)},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                    ],
                })
            else:
                self._context.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": json.dumps(result, ensure_ascii=False),
                })
