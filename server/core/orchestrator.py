import json
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
        tools = skill_registry.to_tools()

        if stream:
            return self._stream_loop(connector, model, tools, skill_registry)
        else:
            return await self._blocking_loop(connector, model, tools, skill_registry)

    async def _blocking_loop(self, connector: LLMConnector, model: str, tools: list, skill_registry) -> str:
        max_iterations = 10
        for _ in range(max_iterations):
            result = await connector.chat(
                messages=self._context,
                model=model,
                tools=tools if tools else None,
                stream=False,
            )

            content = result["content"]
            tool_calls = result["tool_calls"]

            if not tool_calls:
                self._context.append({"role": "assistant", "content": content})
                return content

            assistant_msg = {"role": "assistant", "content": content, "tool_calls": []}
            for tc in tool_calls:
                assistant_msg["tool_calls"].append({
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": json.dumps(tc["arguments"]),
                    },
                })
            self._context.append(assistant_msg)

            for tc in tool_calls:
                skill = skill_registry.get(tc["name"])
                if skill is None:
                    tool_result = {"error": f"Skill '{tc['name']}' not found"}
                else:
                    try:
                        tool_result = await skill.run(**tc["arguments"])
                    except Exception as e:
                        tool_result = {"error": str(e)}

                self._context.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": json.dumps(tool_result),
                })

        return "Maximum iteration limit reached."

    async def _stream_loop(self, connector: LLMConnector, model: str, tools: list, skill_registry) -> AsyncGenerator[str, None]:
        result = await connector.chat(
            messages=self._context,
            model=model,
            tools=tools if tools else None,
            stream=False,
        )

        content = result["content"]
        tool_calls = result["tool_calls"]

        if not tool_calls:
            self._context.append({"role": "assistant", "content": content})
            for char in content:
                yield char
            return

        assistant_msg = {"role": "assistant", "content": content, "tool_calls": []}
        for tc in tool_calls:
            assistant_msg["tool_calls"].append({
                "id": tc["id"],
                "type": "function",
                "function": {
                    "name": tc["name"],
                    "arguments": json.dumps(tc["arguments"]),
                },
            })
        self._context.append(assistant_msg)

        for tc in tool_calls:
            skill = skill_registry.get(tc["name"])
            yield f"[Executing skill: {tc['name']}...]"
            if skill is None:
                tool_result = {"error": f"Skill '{tc['name']}' not found"}
            else:
                try:
                    tool_result = await skill.run(**tc["arguments"])
                except Exception as e:
                    tool_result = {"error": str(e)}

            self._context.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": json.dumps(tool_result),
            })

        final = await self._blocking_loop(connector, model, tools, skill_registry)
        for char in final:
            yield char
