"""
데스크탑 제어 스킬 모음

멀티모달 LLM이 스크린샷을 직접 보고 클릭 좌표를 판단합니다.

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

# ── DPI awareness 설정 ────────────────────────────────────────────────────────
# GetWindowRect, ImageGrab, SetCursorPos가 모두 동일한 물리 좌표를 사용하도록 강제.
# 이 설정이 없으면 Windows 배율(125%, 150% 등)에서 API마다 좌표가 달라짐.
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
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

# 마지막 스크린샷 정보 (클릭 좌표 변환에 사용)
_last_offset: tuple[int, int] = (0, 0)       # client area 화면 좌상단 좌표
_last_scale: tuple[float, float] = (1.0, 1.0)  # 이미지 픽셀 / 화면 좌표 비율


# ── helpers ───────────────────────────────────────────────────────────────────

def _draw_grid(img: "Image.Image") -> "Image.Image":
    """
    이미지 가장자리에 픽셀 좌표 눈금을 그립니다.
    LLM이 리사이즈된 이미지를 보더라도 눈금 숫자를 읽어 원본 좌표를 추정할 수 있게 합니다.
    """
    from PIL import ImageDraw, ImageFont

    img = img.copy()
    draw = ImageDraw.Draw(img)
    w, h = img.size

    try:
        font = ImageFont.truetype("arial.ttf", 14)
    except Exception:
        font = ImageFont.load_default()

    # 눈금 간격: 이미지 크기에 따라 100px 또는 200px 단위
    step = 100 if max(w, h) < 1500 else 200
    tick_len = 10
    color = (255, 0, 0)
    bg = (255, 255, 255)

    # 상단 가로 눈금
    for x in range(0, w, step):
        draw.line([(x, 0), (x, tick_len)], fill=color, width=1)
        label = str(x)
        bbox = draw.textbbox((0, 0), label, font=font)
        tw = bbox[2] - bbox[0]
        tx = max(0, min(x - tw // 2, w - tw))
        draw.rectangle([tx - 1, tick_len, tx + tw + 1, tick_len + 16], fill=bg)
        draw.text((tx, tick_len), label, fill=color, font=font)

    # 좌측 세로 눈금
    for y in range(0, h, step):
        draw.line([(0, y), (tick_len, y)], fill=color, width=1)
        label = str(y)
        bbox = draw.textbbox((0, 0), label, font=font)
        th = bbox[3] - bbox[1]
        ty = max(0, min(y - th // 2, h - th))
        tw = bbox[2] - bbox[0]
        draw.rectangle([tick_len, ty - 1, tick_len + tw + 2, ty + th + 1], fill=bg)
        draw.text((tick_len + 1, ty), label, fill=color, font=font)

    return img


def _img_to_b64(img: "Image.Image") -> str:
    """이미지에 좌표 눈금을 그린 후 JPEG 압축해 base64 반환."""
    img = _draw_grid(img)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=_JPEG_QUALITY)
    return base64.b64encode(buf.getvalue()).decode()


def _get_client_bbox(hwnd: int) -> tuple[int, int, int, int]:
    """
    GetClientRect + ClientToScreen으로 client area(제목줄·테두리 제외)의
    화면 절대 좌표를 반환합니다.
    LLM이 보는 이미지 = client area이므로 좌표가 정확히 일치합니다.
    """
    client = ctypes.wintypes.RECT()
    if not ctypes.windll.user32.GetClientRect(hwnd, ctypes.byref(client)):
        raise RuntimeError("GetClientRect failed")

    pt = ctypes.wintypes.POINT(client.left, client.top)
    if not ctypes.windll.user32.ClientToScreen(hwnd, ctypes.byref(pt)):
        raise RuntimeError("ClientToScreen failed")

    left = pt.x
    top = pt.y
    right = left + (client.right - client.left)
    bottom = top + (client.bottom - client.top)
    return (left, top, right, bottom)


def _focus_window(keyword: str) -> str | None:
    """keyword를 포함하는 창을 찾아 포그라운드로 가져옴."""
    global _focused_hwnd, _focused_title

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
        _focused_hwnd = _focused_title = None
        return None

    hwnd, title = found[0]
    ctypes.windll.user32.ShowWindow(hwnd, 9)        # SW_RESTORE
    ctypes.windll.user32.SetForegroundWindow(hwnd)

    _focused_hwnd = hwnd
    _focused_title = title

    client_bbox = _get_client_bbox(hwnd)
    logging.info(f"[desktop] focused: hwnd={hwnd} client_bbox={client_bbox} title={title!r}")
    return title


def _capture() -> "Image.Image":
    """
    포커스 창의 client area를 ImageGrab.grab(bbox=...)으로 캡처합니다.
    - client area = 제목줄·테두리·그림자 제외 → LLM이 보는 영역과 정확히 일치
    - bbox는 가상 화면 좌표 → 어느 모니터든 캡처 가능
    - DPI scale = img.size / bbox 크기 로 자동 계산
      (DPI-aware 성공 시 1.0, 실패 시 1.25/1.5 등)
    """
    global _last_offset, _last_scale
    from PIL import ImageGrab

    if _focused_hwnd is not None:
        try:
            bbox = _get_client_bbox(_focused_hwnd)
        except Exception as e:
            logging.warning(f"[desktop] GetClientRect failed: {e}, using full screen")
            bbox = None
    else:
        bbox = None

    if bbox:
        img = ImageGrab.grab(bbox=bbox)
        _last_offset = (bbox[0], bbox[1])
        # bbox 면적 vs 이미지 크기로 DPI scale 자동 계산
        bbox_w = bbox[2] - bbox[0]
        bbox_h = bbox[3] - bbox[1]
        scale_x = img.size[0] / bbox_w if bbox_w else 1.0
        scale_y = img.size[1] / bbox_h if bbox_h else 1.0
    else:
        img = ImageGrab.grab(all_screens=True)
        virt_x = ctypes.windll.user32.GetSystemMetrics(76)  # SM_XVIRTUALSCREEN
        virt_y = ctypes.windll.user32.GetSystemMetrics(77)  # SM_YVIRTUALSCREEN
        virt_w = ctypes.windll.user32.GetSystemMetrics(78)  # SM_CXVIRTUALSCREEN
        virt_h = ctypes.windll.user32.GetSystemMetrics(79)  # SM_CYVIRTUALSCREEN
        _last_offset = (virt_x, virt_y)
        scale_x = img.size[0] / virt_w if virt_w else 1.0
        scale_y = img.size[1] / virt_h if virt_h else 1.0

    _last_scale = (scale_x, scale_y)

    logging.info(
        f"[desktop] captured: img={img.size} offset={_last_offset} "
        f"scale=({scale_x:.3f},{scale_y:.3f}) bbox={bbox}"
    )
    return img


def _img_to_screen(img_x: int, img_y: int) -> tuple[int, int]:
    """
    이미지 내 좌표 → 화면 절대 좌표 (SetCursorPos에 사용).
    이미지 픽셀을 scale로 나눠서 화면 좌표로 변환 후 offset 가산.
    scale=1.0이면 나눗셈은 no-op.
    """
    sx, sy = _last_scale
    screen_x = int(img_x / sx) + _last_offset[0]
    screen_y = int(img_y / sy) + _last_offset[1]
    return (screen_x, screen_y)


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
        "포커스된 창의 스크린샷을 찍어 반환합니다. "
        "target을 지정하면 해당 UI 요소의 좌표만 파악합니다. "
        "target이 없으면 전체 화면 상태만 반환합니다."
    )
    parameters = {
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "description": "찾을 UI 요소의 이름 (예: 'PnP Desktop 실행', '로그인 버튼'). 지정하면 해당 요소의 좌표를 파악합니다.",
            }
        },
        "required": [],
    }

    async def run(self, target: str | None = None, **kwargs) -> dict:
        logging.info(f"[desktop] screenshot called, target={target!r}")
        try:
            loop = asyncio.get_event_loop()
            img = await loop.run_in_executor(None, _capture)
            b64 = await loop.run_in_executor(None, _img_to_b64, img)
            w, h = img.size
            window = _focused_title or "전체 화면"

            if target:
                message = (
                    f"스크린샷 ({w}x{h}), 창: {window}.\n"
                    f"이미지 상단과 좌측에 빨간색 픽셀 좌표 눈금이 표시되어 있습니다.\n"
                    f"'{target}' 요소를 찾고, 해당 요소 중앙 위치의 눈금 숫자를 읽어 좌표를 파악하세요.\n"
                    f"반드시 눈금 숫자를 기준으로 x, y 좌표를 결정하세요.\n"
                    f"찾았으면 desktop_click_xy(x, y)로 클릭하세요.\n"
                    f"찾지 못했으면 현재 화면 상태를 설명하세요."
                )
            else:
                message = f"스크린샷 ({w}x{h}), 창: {window}."

            return {
                "status": "success",
                "width": w,
                "height": h,
                "window": window,
                "message": message,
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
        "move_only=true로 설정하면 클릭 없이 커서만 이동하고 스크린샷을 반환합니다. "
        "커서 위치가 맞는지 확인할 때 사용하세요. "
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
            "move_only": {
                "type": "boolean",
                "description": "true면 커서만 이동하고 클릭하지 않음 (디버깅용, 기본값: false)",
            },
        },
        "required": ["x", "y"],
    }

    async def run(
        self, x: int, y: int,
        double_click: bool = False, move_only: bool = False,
        **kwargs,
    ) -> dict:
        logging.info(f"[desktop] click_xy: img=({x},{y}) double={double_click} move_only={move_only}")
        try:
            screen_x, screen_y = _img_to_screen(x, y)
            logging.info(
                f"[desktop] img({x},{y}) + offset{_last_offset} → screen({screen_x},{screen_y})"
            )

            loop = asyncio.get_event_loop()

            def do_action():
                ctypes.windll.user32.SetCursorPos(screen_x, screen_y)
                time.sleep(0.05)
                if not move_only:
                    import pyautogui
                    if double_click:
                        pyautogui.doubleClick()
                    else:
                        pyautogui.click()
                time.sleep(0.1)
                # 최종 커서 위치 확인
                pt = ctypes.wintypes.POINT()
                ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
                return (pt.x, pt.y)

            cursor = await loop.run_in_executor(None, do_action)
            await asyncio.sleep(0.5)

            # 결과 스크린샷 (커서 위치가 보임)
            after_img = await loop.run_in_executor(None, _capture)
            after_b64 = await loop.run_in_executor(None, _img_to_b64, after_img)

            if move_only:
                action = "커서 이동만"
            elif double_click:
                action = "더블클릭"
            else:
                action = "클릭"

            return {
                "status": "success",
                "message": (
                    f"이미지({x},{y}) → 화면({screen_x},{screen_y}) {action} 완료. "
                    f"커서: ({cursor[0]},{cursor[1]})"
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
