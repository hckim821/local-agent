import asyncio
import logging
import os
from pathlib import Path
from .skill_base import SkillBase

# Look for Chromium in these locations (in priority order)
_BROWSERS_DIR = Path(__file__).parent.parent / "browsers"
_CHROME_CANDIDATES = [
    _BROWSERS_DIR / "chrome-win64" / "chrome.exe",  # extracted with folder
    _BROWSERS_DIR / "chrome.exe",                    # extracted flat
    _BROWSERS_DIR / "chrome-win64" / "chrome",       # Linux/Mac
    _BROWSERS_DIR / "chrome",
]


def _find_chrome() -> str | None:
    """Return path to local chrome.exe if found, else None."""
    # Environment variable takes highest priority
    env = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH")
    if env and Path(env).exists():
        return env
    for candidate in _CHROME_CANDIDATES:
        if candidate.exists():
            return str(candidate)
    return None


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
        logging.info(f"[browser_skill] run() called with equipment_id={equipment_id!r}")

        chrome_path = _find_chrome()
        logging.info(f"[browser_skill] Chrome path: {chrome_path}")

        launch_kwargs: dict = {"headless": False, "slow_mo": 500}
        if chrome_path:
            launch_kwargs["executable_path"] = chrome_path
        else:
            logging.warning(
                "[browser_skill] No local chrome found — using Playwright default. "
                f"Searched: {[str(c) for c in _CHROME_CANDIDATES]}"
            )

        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                logging.info("[browser_skill] Playwright started, launching browser...")
                browser = await p.chromium.launch(**launch_kwargs)
                page = await browser.new_page()

                target_url = "https://nxswe.samsungds.net"
                logging.info(f"[browser_skill] Navigating to {target_url}")
                await page.goto(target_url, timeout=30000)
                await asyncio.sleep(2)

                extracted_data: dict = {}
                try:
                    rows = await page.query_selector_all("tr")
                    for row in rows:
                        text = await row.inner_text()
                        if equipment_id in text:
                            extracted_data["row_text"] = text.strip()
                            break
                except Exception as e:
                    logging.warning(f"[browser_skill] Data extraction error: {e}")

                await browser.close()
                logging.info(f"[browser_skill] Done. data={extracted_data}")

                return {
                    "status": "success",
                    "equipment_id": equipment_id,
                    "data": extracted_data,
                    "message": f"설비 {equipment_id} 데이터를 성공적으로 분석했습니다.",
                }

        except Exception as e:
            logging.error(f"[browser_skill] run() failed: {e}", exc_info=True)
            return {
                "status": "error",
                "equipment_id": equipment_id,
                "message": f"설비 분석 오류: {e}",
            }
