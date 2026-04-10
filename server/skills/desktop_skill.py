"""
데스크탑 제어 스킬 모음

tesseract OCR로 화면 텍스트를 감지해 target 버튼의 좌표를 직접 구합니다.
LLM은 좌표 판단에 관여하지 않고, 어떤 버튼을 클릭할지만 결정합니다.

흐름
----
run_application(app_name)
  → desktop_focus_window(title_keyword)
  → desktop_click_text(target="PnP Desktop 실행")  ← OCR로 좌표 찾아서 바로 클릭
  → desktop_screenshot()                           ← 결과 확인용
  → ... (반복)
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

# ── DPI awareness 설정 ────────────────────────────────────────────────────────
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
    logging.info("[desktop] DPI: PROCESS_PER_MONITOR_DPI_AWARE")
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
        logging.info("[desktop] DPI: SetProcessDPIAware (fallback)")
    except Exception:
        logging.warning("[desktop] DPI: failed to set")

_JPEG_QUALITY = 80

# 포커스된 창 정보
_focused_hwnd: int | None = None
_focused_title: str | None = None

# 마지막 캡처 정보 (좌표 변환용)
_last_offset: tuple[int, int] = (0, 0)
_last_scale: tuple[float, float] = (1.0, 1.0)


# ── helpers ───────────────────────────────────────────────────────────────────

def _img_to_b64(img: "Image.Image") -> str:
    """JPEG 압축 후 base64 반환."""
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=_JPEG_QUALITY)
    return base64.b64encode(buf.getvalue()).decode()


def _get_client_bbox(hwnd: int) -> tuple[int, int, int, int]:
    """client area(제목줄·테두리 제외) 화면 절대 좌표."""
    client = ctypes.wintypes.RECT()
    if not ctypes.windll.user32.GetClientRect(hwnd, ctypes.byref(client)):
        raise RuntimeError("GetClientRect failed")
    pt = ctypes.wintypes.POINT(client.left, client.top)
    if not ctypes.windll.user32.ClientToScreen(hwnd, ctypes.byref(pt)):
        raise RuntimeError("ClientToScreen failed")
    return (pt.x, pt.y, pt.x + client.right - client.left, pt.y + client.bottom - client.top)


_FOCUS_TIMEOUT = 10.0   # 창 탐색 최대 대기 시간 (초)
_FOCUS_INTERVAL = 1.0   # 폴링 간격 (초)


def _find_window_once(kw: str) -> tuple[int, str] | None:
    """keyword를 포함하는 창을 1회 탐색. 찾으면 (hwnd, title), 없으면 None."""
    found: list[tuple[int, str]] = []
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
    return found[0] if found else None


def _focus_window(keyword: str) -> str | None:
    """
    keyword를 포함하는 창을 찾아 포그라운드로 가져옴.
    프로그램 실행이 느릴 수 있으므로 최대 10초간 1초 간격으로 폴링합니다.
    """
    global _focused_hwnd, _focused_title

    kw = keyword.lower()
    elapsed = 0.0

    while elapsed < _FOCUS_TIMEOUT:
        result = _find_window_once(kw)
        if result:
            hwnd, title = result
            ctypes.windll.user32.ShowWindow(hwnd, 9)
            ctypes.windll.user32.SetForegroundWindow(hwnd)
            _focused_hwnd = hwnd
            _focused_title = title
            logging.info(f"[desktop] focused: hwnd={hwnd} title={title!r} (after {elapsed:.1f}s)")
            return title
        logging.info(f"[desktop] waiting for '{keyword}'... ({elapsed:.1f}s / {_FOCUS_TIMEOUT}s)")
        time.sleep(_FOCUS_INTERVAL)
        elapsed += _FOCUS_INTERVAL

    _focused_hwnd = _focused_title = None
    logging.warning(f"[desktop] window '{keyword}' not found after {_FOCUS_TIMEOUT}s")
    return None


def _capture() -> "Image.Image":
    """포커스 창 client area 캡처. DPI scale 자동 계산."""
    global _last_offset, _last_scale
    from PIL import ImageGrab

    bbox = None
    if _focused_hwnd is not None:
        try:
            bbox = _get_client_bbox(_focused_hwnd)
        except Exception as e:
            logging.warning(f"[desktop] GetClientRect failed: {e}")

    if bbox:
        img = ImageGrab.grab(bbox=bbox)
        _last_offset = (bbox[0], bbox[1])
        bbox_w = bbox[2] - bbox[0]
        bbox_h = bbox[3] - bbox[1]
        scale_x = img.size[0] / bbox_w if bbox_w else 1.0
        scale_y = img.size[1] / bbox_h if bbox_h else 1.0
    else:
        img = ImageGrab.grab(all_screens=True)
        vx = ctypes.windll.user32.GetSystemMetrics(76)
        vy = ctypes.windll.user32.GetSystemMetrics(77)
        vw = ctypes.windll.user32.GetSystemMetrics(78)
        vh = ctypes.windll.user32.GetSystemMetrics(79)
        _last_offset = (vx, vy)
        scale_x = img.size[0] / vw if vw else 1.0
        scale_y = img.size[1] / vh if vh else 1.0

    _last_scale = (scale_x, scale_y)
    logging.info(f"[desktop] captured: img={img.size} offset={_last_offset} scale=({scale_x:.3f},{scale_y:.3f})")
    return img


def _img_to_screen(img_x: int, img_y: int) -> tuple[int, int]:
    """이미지 내 좌표 → 화면 절대 좌표."""
    sx, sy = _last_scale
    return (int(img_x / sx) + _last_offset[0], int(img_y / sy) + _last_offset[1])


def _ocr_find_target(img: "Image.Image", target: str) -> dict | None:
    """
    tesseract OCR로 이미지에서 target 텍스트의 중앙 좌표를 찾습니다.
    단어 단위로 감지 후 인접 단어를 그룹핑해 전체 문구를 매칭합니다.
    반환: {"x": 이미지내x, "y": 이미지내y, "matched": 매칭된텍스트} 또는 None
    """
    import pytesseract

    data = pytesseract.image_to_data(
        img,
        output_type=pytesseract.Output.DICT,
        lang="kor+eng",
        config="--psm 6",
    )

    n = len(data["text"])
    target_lower = target.lower().strip()
    target_words = target_lower.split()

    # 1) 단어별 정보 수집 (빈 문자열·저신뢰 제외)
    words: list[dict] = []
    for i in range(n):
        text = data["text"][i].strip()
        if not text or int(data["conf"][i]) < 30:
            continue
        words.append({
            "text": text,
            "left": data["left"][i],
            "top": data["top"][i],
            "width": data["width"][i],
            "height": data["height"][i],
            "line": data["line_num"][i],
            "block": data["block_num"][i],
        })

    if not words:
        return None

    # 2) 전체 문구 매칭: 연속 단어 슬라이딩 윈도우
    if len(target_words) > 1:
        for i in range(len(words) - len(target_words) + 1):
            window = words[i : i + len(target_words)]
            # 같은 줄인지 확인
            if any(w["line"] != window[0]["line"] or w["block"] != window[0]["block"] for w in window):
                continue
            joined = " ".join(w["text"] for w in window).lower()
            if target_lower in joined:
                left = min(w["left"] for w in window)
                top = min(w["top"] for w in window)
                right = max(w["left"] + w["width"] for w in window)
                bottom = max(w["top"] + w["height"] for w in window)
                cx = (left + right) // 2
                cy = (top + bottom) // 2
                logging.info(f"[OCR] phrase match: '{joined}' → img({cx},{cy})")
                return {"x": cx, "y": cy, "matched": joined}

    # 3) 단일 단어 / 부분 매칭 (fallback)
    best = None
    best_score = 0
    for w in words:
        wt = w["text"].lower()
        # 완전 일치
        if target_lower == wt:
            cx = w["left"] + w["width"] // 2
            cy = w["top"] + w["height"] // 2
            logging.info(f"[OCR] exact match: '{w['text']}' → img({cx},{cy})")
            return {"x": cx, "y": cy, "matched": w["text"]}
        # 포함 매칭
        if target_lower in wt or wt in target_lower:
            score = len(wt) / len(target_lower) if len(target_lower) > 0 else 0
            if score > best_score:
                best_score = score
                best = w

    if best and best_score > 0.3:
        cx = best["left"] + best["width"] // 2
        cy = best["top"] + best["height"] // 2
        logging.info(f"[OCR] partial match ({best_score:.2f}): '{best['text']}' → img({cx},{cy})")
        return {"x": cx, "y": cy, "matched": best["text"]}

    return None


def _do_click(screen_x: int, screen_y: int, double: bool = False) -> tuple[int, int]:
    """SetCursorPos + click. 커서 최종 위치 반환."""
    import pyautogui
    ctypes.windll.user32.SetCursorPos(screen_x, screen_y)
    time.sleep(0.05)
    if double:
        pyautogui.doubleClick()
    else:
        pyautogui.click()
    time.sleep(0.1)
    pt = ctypes.wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return (pt.x, pt.y)


# ── 스킬 1: 창 포커스 ────────────────────────────────────────────────────────

class DesktopFocusWindowSkill(SkillBase):
    name = "desktop_focus_window"
    description = (
        "창 제목 키워드로 실행 중인 앱을 찾아 포그라운드로 가져옵니다. "
        "run_application 이후 desktop_click_text 전에 반드시 실행하세요."
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
                    "message": f"'{title}' 창을 포그라운드로 가져왔습니다.",
                }
            return {
                "status": "not_found",
                "message": f"'{title_keyword}' 키워드와 일치하는 창을 찾지 못했습니다.",
            }
        except Exception as e:
            logging.error(f"[desktop] focus_window failed: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}


# ── 스킬 2: 스크린샷 (확인용) ────────────────────────────────────────────────

class DesktopScreenshotSkill(SkillBase):
    name = "desktop_screenshot"
    description = "포커스된 창의 스크린샷을 찍어 현재 화면 상태를 확인합니다."
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
                "message": f"스크린샷 ({w}x{h}), 창: {window}.",
                "image_base64": b64,
            }
        except Exception as e:
            logging.error(f"[desktop] screenshot failed: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}


# ── 스킬 3: OCR로 텍스트 찾아서 클릭 ─────────────────────────────────────────

class DesktopClickTextSkill(SkillBase):
    name = "desktop_click_text"
    description = (
        "화면에서 target 텍스트를 OCR로 찾아 해당 위치를 클릭합니다. "
        "LLM이 좌표를 판단할 필요 없이 버튼 이름만 전달하면 됩니다. "
        "클릭 후 새 스크린샷을 반환합니다."
    )
    parameters = {
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "description": "클릭할 UI 요소의 텍스트 (예: 'PnP Desktop 실행', '로그인')",
            },
            "double_click": {
                "type": "boolean",
                "description": "더블클릭 여부 (기본값: false)",
            },
        },
        "required": ["target"],
    }

    async def run(self, target: str, double_click: bool = False, **kwargs) -> dict:
        logging.info(f"[desktop] click_text: target={target!r} double={double_click}")
        try:
            loop = asyncio.get_event_loop()

            # 1) 캡처
            img = await loop.run_in_executor(None, _capture)

            # 2) OCR로 target 검색
            result = await loop.run_in_executor(None, _ocr_find_target, img, target)
            if result is None:
                # 못 찾음 → 스크린샷 반환해서 LLM이 상황 파악
                b64 = await loop.run_in_executor(None, _img_to_b64, img)
                return {
                    "status": "not_found",
                    "message": f"'{target}' 텍스트를 화면에서 찾지 못했습니다. 스크린샷을 확인하세요.",
                    "image_base64": b64,
                    "width": img.size[0],
                    "height": img.size[1],
                }

            # 3) 이미지 좌표 → 화면 좌표 → 클릭
            img_x, img_y = result["x"], result["y"]
            screen_x, screen_y = _img_to_screen(img_x, img_y)
            logging.info(
                f"[desktop] OCR found '{result['matched']}' → "
                f"img({img_x},{img_y}) → screen({screen_x},{screen_y})"
            )

            cursor = await loop.run_in_executor(
                None, _do_click, screen_x, screen_y, double_click
            )
            await asyncio.sleep(0.5)

            # 4) 클릭 후 스크린샷
            after_img = await loop.run_in_executor(None, _capture)
            after_b64 = await loop.run_in_executor(None, _img_to_b64, after_img)

            action = "더블클릭" if double_click else "클릭"
            return {
                "status": "success",
                "message": (
                    f"'{result['matched']}' {action} 완료. "
                    f"이미지({img_x},{img_y}) → 화면({screen_x},{screen_y}), "
                    f"커서: ({cursor[0]},{cursor[1]})"
                ),
                "image_base64": after_b64,
                "width": after_img.size[0],
                "height": after_img.size[1],
            }
        except Exception as e:
            logging.error(f"[desktop] click_text failed: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}


# ── 스킬 4: 좌표 직접 클릭 (fallback) ────────────────────────────────────────

class DesktopClickXYSkill(SkillBase):
    name = "desktop_click_xy"
    description = (
        "이미지 내 좌표 (x, y)를 직접 클릭합니다. "
        "desktop_click_text로 텍스트를 찾지 못했을 때 사용하세요."
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
        logging.info(f"[desktop] click_xy: img=({x},{y}) double={double_click}")
        try:
            screen_x, screen_y = _img_to_screen(x, y)
            logging.info(f"[desktop] img({x},{y}) → screen({screen_x},{screen_y})")

            loop = asyncio.get_event_loop()
            cursor = await loop.run_in_executor(
                None, _do_click, screen_x, screen_y, double_click
            )
            await asyncio.sleep(0.5)

            after_img = await loop.run_in_executor(None, _capture)
            after_b64 = await loop.run_in_executor(None, _img_to_b64, after_img)

            action = "더블클릭" if double_click else "클릭"
            return {
                "status": "success",
                "message": f"({x},{y}) → 화면({screen_x},{screen_y}) {action} 완료. 커서: ({cursor[0]},{cursor[1]})",
                "image_base64": after_b64,
                "width": after_img.size[0],
                "height": after_img.size[1],
            }
        except Exception as e:
            logging.error(f"[desktop] click_xy failed: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}


# ── 스킬 5: 텍스트 입력 ──────────────────────────────────────────────────────

class DesktopTypeSkill(SkillBase):
    name = "desktop_type"
    description = (
        "현재 포커스된 입력 필드에 텍스트를 입력합니다. "
        "desktop_click_text 또는 desktop_click_xy로 입력란을 클릭한 뒤 사용합니다."
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
