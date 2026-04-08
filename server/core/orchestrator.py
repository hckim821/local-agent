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
    ):
        self._context.append({"role": "user", "content": user_message})
        connector = LLMConnector(endpoint_url, api_key)
        tools = skill_registry.to_tools() or None

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
        If tool calls are detected, executes them then streams the follow-up.
        """
        accumulated_content = ""
        tool_calls = []

        # Forward each token immediately as it arrives from the LLM
        async for event in connector.stream_tokens(
            messages=self._context, model=model, tools=tools
        ):
            if event["type"] == "content":
                token = event["value"]
                accumulated_content += token
                yield token
            elif event["type"] == "tool_calls":
                tool_calls = event["value"]

        # Save assistant turn to context
        self._context.append(
            self._build_assistant_msg(accumulated_content, tool_calls)
        )

        if not tool_calls:
            return

        # Execute each skill and stream the final follow-up response
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

            logging.info(f"[Skill] Result: {tool_result}")
            self._context.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": json.dumps(tool_result, ensure_ascii=False),
            })

        # Stream the follow-up response after tool results
        final_content = ""
        async for event in connector.stream_tokens(
            messages=self._context, model=model, tools=None
        ):
            if event["type"] == "content":
                token = event["value"]
                final_content += token
                yield token

        self._context.append({"role": "assistant", "content": final_content})

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

            self._context.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": json.dumps(result, ensure_ascii=False),
            })
