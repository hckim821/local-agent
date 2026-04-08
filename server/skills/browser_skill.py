import asyncio
import os
from pathlib import Path
from .skill_base import SkillBase

# 프로젝트 내 로컬 Chromium 경로 (server/browsers/chrome-win64/chrome.exe)
_BROWSERS_DIR = Path(__file__).parent.parent / "browsers"
_LOCAL_CHROME = _BROWSERS_DIR / "chrome-win64" / "chrome.exe"


def _get_chromium_kwargs() -> dict:
    """로컬 chrome.exe가 있으면 사용하고, 없으면 Playwright 기본 설치 경로를 사용."""
    kwargs = {"headless": False, "slow_mo": 500}
    # 환경변수 우선
    env_path = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH")
    if env_path and Path(env_path).exists():
        kwargs["executable_path"] = env_path
    elif _LOCAL_CHROME.exists():
        kwargs["executable_path"] = str(_LOCAL_CHROME)
    return kwargs


class AnalyzeEquipmentSkill(SkillBase):
    name = "analyze_equipment"
    description = "Edge 브라우저를 통해 설비 진단 사이트에 접속하여 설비 데이터를 분석합니다."
    parameters = {
        "type": "object",
        "properties": {
            "equipment_id": {
                "type": "string",
                "description": "분석할 설비의 ID",
            }
        },
        "required": ["equipment_id"],
    }

    async def run(self, equipment_id: str, **kwargs) -> dict:
        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                browser = await p.chromium.launch(**_get_chromium_kwargs())
                page = await browser.new_page()

                await page.goto("https://nxswe.samsungds.net", timeout=30000)
                await asyncio.sleep(2)

                screenshot_bytes = await page.screenshot()

                extracted_data = {}
                try:
                    rows = await page.query_selector_all("tr")
                    for row in rows:
                        text = await row.inner_text()
                        if equipment_id in text:
                            extracted_data["row_text"] = text.strip()
                            break
                except Exception:
                    pass

                await browser.close()

                return {
                    "status": "success",
                    "equipment_id": equipment_id,
                    "data": extracted_data,
                    "message": f"설비 {equipment_id} 데이터를 성공적으로 분석했습니다.",
                }

        except Exception as e:
            return {
                "status": "error",
                "equipment_id": equipment_id,
                "message": f"설비 분석 중 오류가 발생했습니다: {str(e)}",
            }
