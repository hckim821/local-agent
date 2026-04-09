"""
데스크탑 제어 스킬 모음

전체 화면 스크린샷을 찍고 OCR로 텍스트 요소를 감지해 번호 마커를 오버레이합니다.
edge_skill과 동일한 패턴: screenshot → click_element 를 반복해 데스크탑 앱을 조작합니다.

스킬 목록
----------
desktop_screenshot     : 전체 화면 캡처 + OCR 번호 오버레이 → image_base64 반환
desktop_click_element  : screenshot 번호로 클릭
desktop_click_xy       : 좌표 직접 클릭 (fallback)
desktop_type           : 클립보드 붙여넣기 방식 텍스트 입력
"""

import asyncio
import base64
import io
import logging

from PIL import Image, ImageDraw, ImageFont, ImageGrab
from .skill_base import SkillBase

# 마지막 screenshot의 요소 맵: {번호: {"x": int, "y": int, "text": str}}
_element_map: dict[int, dict] = {}


def _build_annotated_screenshot() -> tuple[str, dict]:
    """
    전체 화면 스크린샷을 찍고 OCR로 텍스트 영역을 감지해 번호 마커를 오버레이합니다.
    pytesseract가 없으면 마커 없이 원본 이미지만 반환합니다.
    (base64 PNG, element_map) 튜플 반환.
    """
    img = ImageGrab.grab()  # 전체 모니터 캡처 (PIL)
    elements: list[dict] = []

    # ── OCR로 텍스트 영역 탐색 ──────────────────────────────────────────────
    try:
        import pytesseract  # type: ignore

        data = pytesseract.image_to_data(
            img,
            output_type=pytesseract.Output.DICT,
            lang="kor+eng",
            config="--psm 11",
        )
        for i in range(len(data["text"])):
            text = data["text"][i].strip()
            conf = int(data["conf"][i])
            w, h = data["width"][i], data["height"][i]
            if text and conf > 60 and w > 8 and h > 8:
                elements.append(
                    {
                        "text": text,
                        "x": data["left"][i] + w // 2,
                        "y": data["top"][i] + h // 2,
                    }
                )
        logging.info(f"[desktop_skill] OCR detected {len(elements)} text regions")
    except Exception as e:
        logging.warning(f"[desktop_skill] OCR unavailable ({e}); returning plain screenshot")

    # ── 번호 마커 오버레이 ────────────────────────────────────────────────────
    img_rgba = img.convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    try:
        font = ImageFont.truetype("arial.ttf", 13)
    except Exception:
        font = ImageFont.load_default()

    element_map: dict[int, dict] = {}
    for i, el in enumerate(elements, start=1):
        x, y = el["x"], el["y"]
        r = 11
        draw.ellipse([x - r, y - r, x + r, y + r], fill=(255, 80, 0, 200))
        label = str(i)
        bbox = draw.textbbox((0, 0), label, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text((x - tw / 2, y - th / 2), label, fill=(255, 255, 255, 255), font=font)
        element_map[i] = {"x": x, "y": y, "text": el["text"]}

    combined = Image.alpha_composite(img_rgba, overlay).convert("RGB")
    buf = io.BytesIO()
    combined.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()

    return b64, element_map


# ── 스킬 1: 전체 화면 스크린샷 ──────────────────────────────────────────────

class DesktopScreenshotSkill(SkillBase):
    name = "desktop_screenshot"
    description = (
        "모니터 전체 화면 스크린샷을 찍습니다. "
        "OCR로 텍스트 요소를 감지해 번호 마커를 표시하고, "
        "번호와 텍스트 목록을 함께 반환합니다. "
        "클릭 전 반드시 이 스킬로 화면 상태를 먼저 확인하세요."
    )
    parameters = {"type": "object", "properties": {}, "required": []}

    async def run(self, **kwargs) -> dict:
        global _element_map
        logging.info("[desktop_skill] desktop_screenshot called")
        try:
            loop = asyncio.get_event_loop()
            b64, _element_map = await loop.run_in_executor(
                None, _build_annotated_screenshot
            )

            import pyautogui
            w, h = pyautogui.size()
            elements_summary = {str(n): info["text"] for n, info in _element_map.items()}
            logging.info(
                f"[desktop_skill] Screenshot captured ({w}x{h}), "
                f"{len(_element_map)} elements annotated"
            )
            return {
                "status": "success",
                "resolution": f"{w}x{h}",
                "elements": elements_summary,
                "image_base64": b64,
            }
        except Exception as e:
            logging.error(f"[desktop_skill] desktop_screenshot failed: {e}", exc_info=True)
            return {"status": "error", "message": f"스크린샷 오류: {e}"}


# ── 스킬 2: 번호로 요소 클릭 ────────────────────────────────────────────────

class DesktopClickElementSkill(SkillBase):
    name = "desktop_click_element"
    description = (
        "desktop_screenshot에서 표시된 번호로 화면 요소를 클릭합니다. "
        "반드시 desktop_screenshot을 먼저 실행해 번호를 확인한 뒤 사용하세요."
    )
    parameters = {
        "type": "object",
        "properties": {
            "number": {
                "type": "integer",
                "description": "클릭할 요소의 번호 (desktop_screenshot 이미지에 표시된 번호)",
            }
        },
        "required": ["number"],
    }

    async def run(self, number: int, **kwargs) -> dict:
        global _element_map
        logging.info(f"[desktop_skill] desktop_click_element: number={number}")
        try:
            if not _element_map:
                return {
                    "status": "error",
                    "message": "먼저 desktop_screenshot을 실행해 요소 목록을 확인하세요.",
                }
            el = _element_map.get(number)
            if el is None:
                return {
                    "status": "error",
                    "message": (
                        f"번호 {number}에 해당하는 요소가 없습니다. "
                        f"유효 범위: 1~{max(_element_map.keys())}"
                    ),
                }

            import pyautogui

            pyautogui.click(int(el["x"]), int(el["y"]))
            await asyncio.sleep(0.5)
            logging.info(
                f"[desktop_skill] Clicked element {number}: "
                f"'{el['text']}' at ({el['x']}, {el['y']})"
            )
            return {
                "status": "success",
                "message": f"요소 {number} ('{el['text']}') 클릭 완료",
                "x": el["x"],
                "y": el["y"],
            }
        except Exception as e:
            logging.error(
                f"[desktop_skill] desktop_click_element failed: {e}", exc_info=True
            )
            return {"status": "error", "message": f"클릭 오류: {e}"}


# ── 스킬 3: 좌표 직접 클릭 (fallback) ───────────────────────────────────────

class DesktopClickXYSkill(SkillBase):
    name = "desktop_click_xy"
    description = (
        "화면의 특정 좌표를 직접 클릭합니다. "
        "desktop_click_element로 번호를 찾지 못했거나 정확한 좌표를 알 때 사용하세요. "
        "double_click을 true로 설정하면 더블클릭합니다."
    )
    parameters = {
        "type": "object",
        "properties": {
            "x": {"type": "number", "description": "클릭할 X 좌표 (픽셀)"},
            "y": {"type": "number", "description": "클릭할 Y 좌표 (픽셀)"},
            "double_click": {
                "type": "boolean",
                "description": "더블클릭 여부 (기본값: false)",
            },
        },
        "required": ["x", "y"],
    }

    async def run(
        self, x: float, y: float, double_click: bool = False, **kwargs
    ) -> dict:
        logging.info(
            f"[desktop_skill] desktop_click_xy: ({x}, {y}) double={double_click}"
        )
        try:
            import pyautogui

            if double_click:
                pyautogui.doubleClick(int(x), int(y))
            else:
                pyautogui.click(int(x), int(y))
            await asyncio.sleep(0.3)
            action = "더블클릭" if double_click else "클릭"
            return {
                "status": "success",
                "message": f"좌표 ({int(x)}, {int(y)}) {action} 완료",
            }
        except Exception as e:
            logging.error(f"[desktop_skill] desktop_click_xy failed: {e}", exc_info=True)
            return {"status": "error", "message": f"클릭 오류: {e}"}


# ── 스킬 4: 텍스트 입력 ──────────────────────────────────────────────────────

class DesktopTypeSkill(SkillBase):
    name = "desktop_type"
    description = (
        "현재 포커스된 입력 필드에 텍스트를 입력합니다. "
        "desktop_click_element 또는 desktop_click_xy로 입력란을 클릭한 뒤 사용합니다. "
        "press_enter를 true로 설정하면 입력 후 Enter를 누릅니다."
    )
    parameters = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "입력할 텍스트"},
            "press_enter": {
                "type": "boolean",
                "description": "입력 후 Enter 키 입력 여부 (기본값: false)",
            },
        },
        "required": ["text"],
    }

    async def run(self, text: str, press_enter: bool = False, **kwargs) -> dict:
        logging.info(f"[desktop_skill] desktop_type: text={text!r} enter={press_enter}")
        try:
            import pyperclip
            import pyautogui

            pyperclip.copy(text)
            pyautogui.hotkey("ctrl", "v")
            await asyncio.sleep(0.3)
            if press_enter:
                pyautogui.press("enter")
                await asyncio.sleep(0.3)
            return {"status": "success", "message": f"텍스트 입력 완료: {text!r}"}
        except Exception as e:
            logging.error(f"[desktop_skill] desktop_type failed: {e}", exc_info=True)
            return {"status": "error", "message": f"텍스트 입력 오류: {e}"}
