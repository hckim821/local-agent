from .skill_base import SkillBase


class AnalyzeImageSkill(SkillBase):
    """
    이미지 분석 스킬.
    실제 처리는 Orchestrator가 멀티모달 메시지로 LLM에 직접 전달하므로
    이 run()은 호출되지 않습니다. 스킬 패널 표시 및 확장성 목적으로 등록합니다.
    """

    name = "analyze_image"
    description = (
        "채팅 입력창에 이미지를 붙여넣기(Ctrl+V)하면 자동으로 활성화됩니다. "
        "LLM이 이미지 내용을 분석하여 답변합니다. (Vision 모델 필요)"
    )
    parameters = {
        "type": "object",
        "properties": {
            "image": {
                "type": "string",
                "description": "분석할 이미지 (base64 data URL)",
            },
            "question": {
                "type": "string",
                "description": "이미지에 대한 질문 (선택)",
            },
        },
        "required": ["image"],
    }

    async def run(self, image: str = "", question: str = "", **kwargs) -> dict:
        return {
            "status": "info",
            "message": "이미지 분석은 Orchestrator가 직접 처리합니다.",
        }
