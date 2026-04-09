"""
스킬 기반 에이전트 러너

사용자의 자연어 요청을 Claude API에 전달하고,
Claude가 필요한 스킬을 순차적으로 tool_use로 호출하면 실행한 뒤
결과를 다시 Claude에 전달하는 루프를 반복합니다.

사용법:
  python agent_runner.py "https://naver.com으로 이동한 뒤 스크린샷을 찍어줘. 상단 링크에 지도가 보이면 클릭해줘."
"""

import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

MODEL = "claude-sonnet-4-6"


def _show_image(b64: str) -> None:
    """base64 PNG를 메모리에서 PIL로 열어 이미지 뷰어에 표시합니다."""
    import base64 as _b64
    import io
    from PIL import Image

    data = _b64.b64decode(b64)
    img = Image.open(io.BytesIO(data))
    img.show(title="edge_screenshot")
MAX_TURNS = 10  # 무한루프 방지


def build_tools(skill_registry) -> list[dict]:
    """스킬 레지스트리를 Claude tool 형식으로 변환합니다."""
    tools = []
    for skill_info in skill_registry.list_all():
        tools.append({
            "name": skill_info["name"],
            "description": skill_info["description"],
            "input_schema": skill_info["parameters"],
        })
    return tools


async def run_agent(user_message: str) -> str:
    from skills import skill_registry
    import anthropic

    skill_registry.load_skills()
    tools = build_tools(skill_registry)
    client = anthropic.Anthropic()

    messages = [{"role": "user", "content": user_message}]

    logging.info(f"[agent] 시작: {user_message!r}")
    logging.info(f"[agent] 사용 가능한 스킬: {[t['name'] for t in tools]}")

    for turn in range(MAX_TURNS):
        logging.info(f"[agent] ── Turn {turn + 1} ──────────────────────────")

        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            tools=tools,
            messages=messages,
        )

        logging.info(f"[agent] stop_reason={response.stop_reason}")

        # Claude의 응답을 messages에 추가
        messages.append({"role": "assistant", "content": response.content})

        # 텍스트만 반환 → 완료
        if response.stop_reason == "end_turn":
            final_text = next(
                (b.text for b in response.content if hasattr(b, "text")), ""
            )
            logging.info(f"[agent] 완료")
            return final_text

        # tool_use 블록 처리
        if response.stop_reason == "tool_use":
            tool_results = []

            for block in response.content:
                if block.type != "tool_use":
                    continue

                skill_name = block.name
                skill_input = block.input
                tool_use_id = block.id

                logging.info(f"[agent] 스킬 호출: {skill_name}({json.dumps(skill_input, ensure_ascii=False)})")

                skill = skill_registry.get(skill_name)
                if skill is None:
                    result = {"status": "error", "message": f"스킬 '{skill_name}'을 찾을 수 없습니다."}
                else:
                    try:
                        result = await skill.run(**skill_input)
                    except Exception as e:
                        result = {"status": "error", "message": str(e)}

                logging.info(f"[agent] 결과: status={result.get('status')}")

                # 스크린샷이면 이미지 뷰어로 즉시 표시 + Claude 비전으로 전달
                if "image_base64" in result:
                    b64 = result.pop("image_base64")
                    _show_image(b64)
                    content = [
                        {"type": "text", "text": json.dumps(result, ensure_ascii=False)},
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": b64,
                            },
                        },
                    ]
                else:
                    content = json.dumps(result, ensure_ascii=False)

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": content,
                })

            messages.append({"role": "user", "content": tool_results})

    return "[agent] 최대 턴 수에 도달했습니다."


async def main():
    if len(sys.argv) < 2:
        print("사용법: python agent_runner.py \"<질문>\"")
        print('예시: python agent_runner.py "https://naver.com으로 이동한 뒤 스크린샷을 찍어줘."')
        return

    user_message = " ".join(sys.argv[1:])
    result = await run_agent(user_message)

    print("\n── 최종 응답 ─────────────────────────────────────────")
    print(result)
    print("─────────────────────────────────────────────────────\n")


if __name__ == "__main__":
    asyncio.run(main())
