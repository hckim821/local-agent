"""
데스크탑 제어 스킬 모음

전체 화면 스크린샷을 찍고 OCR로 텍스트 요소를 감지해 번호 마커를 오버레이합니다.
edge_skill과 동일한 패턴: screenshot → click_element 를 반복해 데스크탑 앱을 조작합니다.

권장 흐름
----------
run_application(app_name)
  → desktop_focus_window(title_keyword)   ← 앱 포커스 확보
  → desktop_screenshot()                  ← 포커스된 화면 캡처
  → desktop_click_element(N) / desktop_click_xy(x, y)
  → desktop_screenshot() → ... (목적 달성까지 반복)

스킬 목록
----------
desktop_focus_window   : 창 제목으로 앱을 포그라운드로 가져옴
desktop_screenshot     : 전체 화면 캡처 + OCR 번호 오버레이 → image_base64 반환
desktop_click_element  : screenshot 번호로 클릭
desktop_click_xy       : 좌표 직접 클릭 (fallback)
desktop_type           : 클립보드 붙여넣기 방식 텍스트 입력
"""

import asyncio
import base64
import ctypes
import ctypes.wintypes
import io
import logging

from PIL import Image, ImageDraw, ImageFont, ImageGrab
from .skill_base import SkillBase

# 마지막 screenshot의 요소 맵: {번호: {"x": int, "y": int, "text": str}}
_element_map: dict[int, dict] = {}


# ── DPI 스케일 보정 ───────────────────────────────────────────────────────────

def _get_dpi_scale() -> tuple[float, float]:
    """
    ImageGrab 물리 픽셀과 pyautogui 논리 좌표의 비율을 반환.
    DPI 스케일링(예: 150%)이 걸려 있으면 1.5 등의 값이 나온다.
    OCR 좌표(물리 px) → pyautogui 클릭 좌표(논리 px) 변환에 사용.
    """
    try:
        import pyautogui
        logical_w, logical_h = pyautogui.size()
        probe = ImageGrab.grab()
        phys_w, phys_h = probe.size
        return phys_w / logical_w, phys_h / logical_h
    except Exception:
        return 1.0, 1.0


# ── 창 포커스 helpers ─────────────────────────────────────────────────────────

def _focus_window_by_keyword(keyword: str) -> str | None:
    """
    keyword를 포함하는 최상위 창을 찾아 포그라운드로 가져옵니다.
    성공 시 창 제목, 실패 시 None 반환.
    """
    found_hwnd: list[int] = []
    found_title: list[str] = []
    kw = keyword.lower()

    EnumProc = ctypes.WINFUNCTYPE(
        ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM
    )

    def _cb(hwnd: int, _: int) -> bool:
        if not ctypes.windll.user32.IsWindowVisible(hwnd):
            return True
        n = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        if n == 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, n + 1)
        if kw in buf.value.lower():
            found_hwnd.append(hwnd)
            found_title.append(buf.value)
            return False  # 첫 번째 매칭만
        return True

    ctypes.windll.user32.EnumWindows(EnumProc(_cb), 0)

    if not found_hwnd:
        return None

    hwnd = found_hwnd[0]
    SW_RESTORE = 9
    ctypes.windll.user32.ShowWindow(hwnd, SW_RESTORE)   # 최소화 복원
    ctypes.windll.user32.SetForegroundWindow(hwnd)       # 포그라운드
    return found_title[0]


# ── OCR + 오버레이 ────────────────────────────────────────────────────────────

def _build_annotated_screenshot() -> tuple[str, dict]:
    """
    전체 화면 스크린샷을 찍고 OCR로 텍스트 영역을 감지해 번호 마커를 오버레이합니다.
    좌표는 DPI 스케일을 보정해 pyautogui 논리 좌표로 저장합니다.
    pytesseract가 없으면 마커 없이 원본 이미지만 반환합니다.
    반환: (base64 PNG 문자열, element_map)
    """
    img = ImageGrab.grab()  # 전체 모니터 캡처
    scale_x, scale_y = _get_dpi_scale()
    logging.info(f"[desktop_skill] DPI scale: x={scale_x:.3f} y={scale_y:.3f}, "
                 f"captured={img.size}")

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
                # 물리 픽셀 중심 좌표 → 논리 좌표로 보정
                phys_cx = data["left"][i] + w // 2
                phys_cy = data["top"][i] + h // 2
                elements.append(
                    {
                        "text": text,
                        "x": int(phys_cx / scale_x),
                        "y": int(phys_cy / scale_y),
                    }
                )
        logging.info(f"[desktop_skill] OCR detected {len(elements)} text regions")
    except Exception as e:
        logging.warning(f"[desktop_skill] OCR unavailable ({e}); returning plain screenshot")

    # ── 번호 마커 오버레이 (이미지 좌표 = 물리 픽셀) ─────────────────────────
    img_rgba = img.convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    try:
        font = ImageFont.truetype("arial.ttf", 13)
    except Exception:
        font = ImageFont.load_default()

    element_map: dict[int, dict] = {}
    for i, el in enumerate(elements, start=1):
        # 오버레이는 이미지(물리 픽셀) 기준으로 그려야 정확히 맞음
        phys_x = int(el["x"] * scale_x)
        phys_y = int(el["y"] * scale_y)
        r = 11
        draw.ellipse([phys_x - r, phys_y - r, phys_x + r, phys_y + r], fill=(255, 80, 0, 200))
        label = str(i)
        bbox = draw.textbbox((0, 0), label, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text(
            (phys_x - tw / 2, phys_y - th / 2),
            label,
            fill=(255, 255, 255, 255),
            font=font,
        )
        # element_map에는 논리 좌표 저장 (pyautogui 클릭용)
        element_map[i] = {"x": el["x"], "y": el["y"], "text": el["text"]}

    combined = Image.alpha_composite(img_rgba, overlay).convert("RGB")
    buf = io.BytesIO()
    combined.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()

    return b64, element_map


# ── 스킬 0: 창 포커스 ────────────────────────────────────────────────────────

class DesktopFocusWindowSkill(SkillBase):
    name = "desktop_focus_window"
    description = (
        "창 제목 키워드로 실행 중인 앱을 찾아 포그라운드로 가져옵니다. "
        "run_application 이후 desktop_screenshot 전에 반드시 이 스킬을 실행해 "
        "앱이 화면 앞에 오도록 하세요. "
        "title_keyword에는 run_application이 반환한 window_title을 사용하세요."
    )
    parameters = {
        "type": "object",
        "properties": {
            "title_keyword": {
                "type": "string",
                "description": "포커스할 창 제목에 포함된 키워드 (부분 일치)",
            }
        },
        "required": ["title_keyword"],
    }

    async def run(self, title_keyword: str, **kwargs) -> dict:
        logging.info(f"[desktop_skill] desktop_focus_window: {title_keyword!r}")
        try:
            loop = asyncio.get_event_loop()
            title = await loop.run_in_executor(
                None, _focus_window_by_keyword, title_keyword
            )
            if title:
                await asyncio.sleep(0.5)  # 포그라운드 전환 안정화
                logging.info(f"[desktop_skill] Window focused: {title!r}")
                return {
                    "status": "success",
                    "window_title": title,
                    "message": f"'{title}' 창을 포그라운드로 가져왔습니다. 이제 desktop_screenshot을 실행하세요.",
                }
            else:
                return {
                    "status": "not_found",
                    "message": (
                        f"'{title_keyword}' 키워드와 일치하는 창을 찾지 못했습니다. "
                        "앱이 실행 중인지 확인하거나 키워드를 수정해 주세요."
                    ),
                }
        except Exception as e:
            logging.error(f"[desktop_skill] desktop_focus_window failed: {e}", exc_info=True)
            return {"status": "error", "message": f"창 포커스 오류: {e}"}


# ── 스킬 1: 전체 화면 스크린샷 ──────────────────────────────────────────────

class DesktopScreenshotSkill(SkillBase):
    name = "desktop_screenshot"
    description = (
        "모니터 전체 화면 스크린샷을 찍습니다. "
        "OCR로 텍스트 요소를 감지해 번호 마커를 표시하고, "
        "번호와 텍스트 목록을 함께 반환합니다. "
        "desktop_focus_window로 앱을 포그라운드로 가져온 뒤 이 스킬을 실행하세요."
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
                f"[desktop_skill] Screenshot ready ({w}x{h} logical), "
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

            x, y = int(el["x"]), int(el["y"])
            logging.info(
                f"[desktop_skill] Clicking element {number}: "
                f"'{el['text']}' at logical ({x}, {y})"
            )
            pyautogui.click(x, y)
            await asyncio.sleep(0.5)
            return {
                "status": "success",
                "message": f"요소 {number} ('{el['text']}') 클릭 완료 — 좌표 ({x}, {y})",
                "x": x,
                "y": y,
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
        "화면의 특정 논리 좌표를 직접 클릭합니다. "
        "desktop_click_element로 번호를 찾지 못했거나 정확한 좌표를 알 때 사용하세요. "
        "double_click을 true로 설정하면 더블클릭합니다."
    )
    parameters = {
        "type": "object",
        "properties": {
            "x": {"type": "number", "description": "클릭할 X 좌표 (논리 픽셀)"},
            "y": {"type": "number", "description": "클릭할 Y 좌표 (논리 픽셀)"},
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
