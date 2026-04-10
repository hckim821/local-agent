"""
데스크탑 제어 스킬 모음

멀티모달 LLM이 스크린샷을 직접 보고 클릭 좌표를 판단합니다.
OCR 의존 없이 pyautogui 좌표 공간에서 캡처+클릭을 처리합니다.

흐름
----
run_application(app_name)
  → desktop_focus_window(title_keyword)
  → desktop_screenshot()          ← LLM이 이미지를 보고 좌표 판단
  → desktop_click_xy(x, y)        ← 이미지 내 좌표로 클릭
  → desktop_screenshot() → ...    (목적 달성까지 반복)
"""

import asyncio
import base64
import ctypes
import ctypes.wintypes
import io
import logging
import time

from PIL import Image
from .skill_base import SkillBase

_JPEG_QUALITY = 80

# 포커스된 창 정보
_focused_hwnd: int | None = None
_focused_rect: tuple[int, int, int, int] | None = None  # (left, top, right, bottom)
_focused_title: str | None = None

# 마지막 스크린샷 정보 (클릭 좌표 변환에 사용)
_last_offset: tuple[int, int] = (0, 0)      # 캡처 영역의 pyautogui 좌표 (left, top)
_last_scale: tuple[float, float] = (1.0, 1.0)  # 이미지 px / pyautogui 좌표


# ── helpers ───────────────────────────────────────────────────────────────────

def _img_to_b64(img: "Image.Image") -> str:
    """이미지를 JPEG 압축 후 base64 반환."""
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=_JPEG_QUALITY)
    return base64.b64encode(buf.getvalue()).decode()


def _focus_window(keyword: str) -> str | None:
    """keyword를 포함하는 창을 찾아 포그라운드로 가져옴. HWND/RECT 저장."""
    global _focused_hwnd, _focused_rect, _focused_title

    found: list[tuple[int, str]] = []
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
            found.append((hwnd, buf.value))
            return False
        return True

    ctypes.windll.user32.EnumWindows(EnumProc(_cb), 0)

    if not found:
        _focused_hwnd = _focused_rect = _focused_title = None
        return None

    hwnd, title = found[0]
    ctypes.windll.user32.ShowWindow(hwnd, 9)        # SW_RESTORE
    ctypes.windll.user32.SetForegroundWindow(hwnd)

    rect = ctypes.wintypes.RECT()
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    _focused_hwnd = hwnd
    _focused_rect = (rect.left, rect.top, rect.right, rect.bottom)
    _focused_title = title

    logging.info(f"[desktop] focused: hwnd={hwnd} rect={_focused_rect} title={title!r}")
    return title


def _capture() -> "Image.Image":
    """
    전체 화면을 캡처한 뒤, 포커스 창 영역만 직접 crop합니다.
    스케일 보정:
      full_img.size  = 물리 해상도 (예: 2880x1620)
      pyautogui.size = 논리 해상도 (예: 1920x1080)
      scale = 물리/논리 (예: 1.5)
      crop은 논리 좌표 * scale 로 이미지 픽셀 좌표로 변환해서 수행.
    """
    global _last_offset, _last_scale, _focused_rect, _focused_hwnd
    import pyautogui

    # 1) 전체 화면 캡처
    full = pyautogui.screenshot()
    gui_w, gui_h = pyautogui.size()
    img_w, img_h = full.size
    scale_x = img_w / gui_w
    scale_y = img_h / gui_h

    logging.info(
        f"[desktop] full capture: img={full.size} gui=({gui_w},{gui_h}) "
        f"scale=({scale_x:.3f},{scale_y:.3f})"
    )

    # 2) 포커스 창 영역으로 crop
    offset_x, offset_y = 0, 0  # pyautogui 좌표 공간
    if _focused_hwnd is not None:
        rect = ctypes.wintypes.RECT()
        if ctypes.windll.user32.GetWindowRect(_focused_hwnd, ctypes.byref(rect)):
            _focused_rect = (rect.left, rect.top, rect.right, rect.bottom)
            left, top, right, bottom = _focused_rect
            offset_x, offset_y = left, top
            # 논리 좌표 → 이미지 픽셀 좌표로 변환해서 crop
            crop_box = (
                int(left * scale_x), int(top * scale_y),
                int(right * scale_x), int(bottom * scale_y),
            )
            full = full.crop(crop_box)
            logging.info(
                f"[desktop] window rect(gui): ({left},{top},{right},{bottom}) "
                f"→ crop(px): {crop_box} → cropped: {full.size}"
            )

    _last_offset = (offset_x, offset_y)
    _last_scale = (scale_x, scale_y)
    return full


def _img_to_screen(img_x: int, img_y: int) -> tuple[int, int]:
    """
    이미지 내 좌표 → pyautogui 화면 절대 좌표.
    이미지 픽셀은 물리 해상도이므로 scale로 나눠서 논리 좌표로 변환 후 offset 더함.
    """
    sx, sy = _last_scale
    gui_x = int(img_x / sx) + _last_offset[0]
    gui_y = int(img_y / sy) + _last_offset[1]
    return (gui_x, gui_y)


# ── 스킬 1: 창 포커스 ────────────────────────────────────────────────────────

class DesktopFocusWindowSkill(SkillBase):
    name = "desktop_focus_window"
    description = (
        "창 제목 키워드로 실행 중인 앱을 찾아 포그라운드로 가져옵니다. "
        "run_application 이후 desktop_screenshot 전에 반드시 실행하세요."
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
        logging.info(f"[desktop] focus_window: {title_keyword!r}")
        try:
            loop = asyncio.get_event_loop()
            title = await loop.run_in_executor(None, _focus_window, title_keyword)
            if title:
                await asyncio.sleep(0.5)
                return {
                    "status": "success",
                    "window_title": title,
                    "window_rect": _focused_rect,
                    "message": f"'{title}' 창을 포그라운드로 가져왔습니다.",
                }
            return {
                "status": "not_found",
                "message": f"'{title_keyword}' 키워드와 일치하는 창을 찾지 못했습니다.",
            }
        except Exception as e:
            logging.error(f"[desktop] focus_window failed: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}


# ── 스킬 2: 스크린샷 ─────────────────────────────────────────────────────────

class DesktopScreenshotSkill(SkillBase):
    name = "desktop_screenshot"
    description = (
        "포커스된 창(또는 전체 화면)의 스크린샷을 찍어 반환합니다. "
        "이미지의 좌상단이 (0,0)이고 우하단이 (width,height)입니다. "
        "클릭할 위치를 이미지 내 (x, y) 좌표로 파악한 뒤 "
        "desktop_click_xy에 전달하세요."
    )
    parameters = {"type": "object", "properties": {}, "required": []}

    async def run(self, **kwargs) -> dict:
        logging.info("[desktop] screenshot called")
        try:
            loop = asyncio.get_event_loop()
            img = await loop.run_in_executor(None, _capture)
            b64 = await loop.run_in_executor(None, _img_to_b64, img)
            w, h = img.size
            window = _focused_title or "전체 화면"
            return {
                "status": "success",
                "width": w,
                "height": h,
                "window": window,
                "message": f"스크린샷 ({w}x{h}). 이미지를 보고 클릭할 좌표를 desktop_click_xy로 전달하세요.",
                "image_base64": b64,
            }
        except Exception as e:
            logging.error(f"[desktop] screenshot failed: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}


# ── 스킬 3: 좌표 클릭 ────────────────────────────────────────────────────────

class DesktopClickXYSkill(SkillBase):
    name = "desktop_click_xy"
    description = (
        "desktop_screenshot 이미지 내 좌표 (x, y)를 클릭합니다. "
        "이미지 왼쪽 상단이 (0, 0)입니다. "
        "스크린샷에서 클릭할 위치의 x, y 좌표를 전달하세요. "
        "클릭 후 새 스크린샷을 자동으로 찍어 반환합니다."
    )
    parameters = {
        "type": "object",
        "properties": {
            "x": {"type": "integer", "description": "이미지 내 X 좌표"},
            "y": {"type": "integer", "description": "이미지 내 Y 좌표"},
            "double_click": {
                "type": "boolean",
                "description": "더블클릭 여부 (기본값: false)",
            },
        },
        "required": ["x", "y"],
    }

    async def run(self, x: int, y: int, double_click: bool = False, **kwargs) -> dict:
        import pyautogui

        logging.info(f"[desktop] click_xy: img=({x},{y}) double={double_click}")
        try:
            # 이미지 좌표 → 화면 절대 좌표
            screen_x, screen_y = _img_to_screen(x, y)
            logging.info(
                f"[desktop] img({x},{y}) + offset{_last_offset} → screen({screen_x},{screen_y})"
            )

            # 클릭
            loop = asyncio.get_event_loop()
            def do_click():
                if double_click:
                    pyautogui.doubleClick(screen_x, screen_y)
                else:
                    pyautogui.click(screen_x, screen_y)
                time.sleep(0.1)
                pos = pyautogui.position()
                logging.info(f"[desktop] cursor after click: {pos}")
                return pos

            cursor = await loop.run_in_executor(None, do_click)
            await asyncio.sleep(0.5)

            # 클릭 후 스크린샷
            after_img = await loop.run_in_executor(None, _capture)
            after_b64 = await loop.run_in_executor(None, _img_to_b64, after_img)

            action = "더블클릭" if double_click else "클릭"
            return {
                "status": "success",
                "message": (
                    f"이미지({x},{y}) → 화면({screen_x},{screen_y}) {action} 완료. "
                    f"커서 위치: ({cursor[0]},{cursor[1]})"
                ),
                "image_base64": after_b64,
                "width": after_img.size[0],
                "height": after_img.size[1],
            }
        except Exception as e:
            logging.error(f"[desktop] click_xy failed: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}


# ── 스킬 4: 텍스트 입력 ──────────────────────────────────────────────────────

class DesktopTypeSkill(SkillBase):
    name = "desktop_type"
    description = (
        "현재 포커스된 입력 필드에 텍스트를 입력합니다. "
        "desktop_click_xy로 입력란을 클릭한 뒤 사용합니다."
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
        logging.info(f"[desktop] type: text={text!r} enter={press_enter}")
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
            logging.error(f"[desktop] type failed: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}
