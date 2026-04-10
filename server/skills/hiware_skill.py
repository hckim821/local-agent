import logging
import re
from .skill_base import SkillBase


class HiwareUserRequestSkill(SkillBase):
    name = "hiware_user_request"
    description = (
        "Hiware 사용자 신청용 CSV를 생성합니다. "
        "사용자 ID 목록을 받아 'id,appuser' 형식의 CSV를 반환합니다. "
        "사용자 등록, 계정 신청, hiware 사용자 추가 요청 시 호출합니다."
    )
    parameters = {
        "type": "object",
        "properties": {
            "user_ids": {
                "type": "string",
                "description": (
                    "사용자 ID 목록. 줄바꿈(\\n) 또는 쉼표(,)로 구분. "
                    "예: 'user1\\nuser2\\nuser3'"
                ),
            },
            "account": {
                "type": "string",
                "description": "서버 접속 계정 (예: root, appuser). 사용자가 언급한 계정명을 그대로 전달.",
            },
        },
        "required": ["user_ids", "account"],
    }

    async def run(self, user_ids: str, account: str = "root", **kwargs) -> dict:
        logging.info(f"[hiware_skill] hiware_user_request: user_ids={user_ids!r} account={account!r}")

        # 줄바꿈 / 쉼표 / 공백으로 분리 후 빈 항목 제거
        ids = [
            uid.strip()
            for uid in re.split(r"[\n,]+", user_ids)
            if uid.strip()
        ]

        if not ids:
            return {
                "status": "error",
                "message": "사용자 ID가 없습니다. ID 목록을 입력해 주세요.",
            }

        tsv_lines = [f"{uid}\t{account}" for uid in ids]
        tsv_text = "\n".join(tsv_lines)

        logging.info(f"[hiware_skill] Generated TSV for {len(ids)} users")

        return {
            "status": "success",
            "count": len(ids),
            "tsv": tsv_text,
            "message": (
                f"Hiware 사용자 신청 ({len(ids)}명):\n\n"
                f"```\n{tsv_text}\n```"
            ),
        }
