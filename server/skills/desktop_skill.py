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
import time

from PIL import Image, ImageDraw, ImageFont, ImageGrab
from .skill_base import SkillBase


# ── DPI awareness 설정 ────────────────────────────────────────────────────────
# ImageGrab(PIL)과 pyautogui가 동일한 좌표 공간(물리 픽셀)을 사용하도록 설정.
# 이 호출이 없으면 ImageGrab은 물리 해상도, pyautogui는 논리 해상도를 써서
# 좌표가 DPI 배율만큼 어긋남.
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
    logging.info("[desktop_skill] DPI awareness: PROCESS_PER_MONITOR_DPI_AWARE")
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
        logging.info("[desktop_skill] DPI awareness: SetProcessDPIAware (fallback)")
    except Exception:
        logging.warning("[desktop_skill] DPI awareness: failed to set")


# ── 클릭 helper ──────────────────────────────────────────────────────────────

def _do_click(x: int, y: int, double: bool = False) -> dict:
    """pyautogui.click(x, y)로 클릭합니다. 관리자 권한 CMD에서 실행 필요."""
    import pyautogui

    before = pyautogui.position()
    logging.info(f"[desktop_skill] click target=({x},{y}) cursor_before={before}")

    if double:
        pyautogui.doubleClick(x, y)
    else:
        pyautogui.click(x, y)

    time.sleep(0.1)
    after = pyautogui.position()
    cursor_ok = abs(after[0] - x) <= 2 and abs(after[1] - y) <= 2
    logging.info(f"[desktop_skill] click done cursor_after={after} ok={cursor_ok}")

    return {"cursor_ok": cursor_ok, "cursor_at": (after[0], after[1])}

# 마지막 screenshot 상태 (클릭 미리보기 렌더링에 재사용)
_element_map: dict[int, dict] = {}
_last_raw_img: "Image.Image | None" = None   # OCR 전 원본 이미지
_last_scale: tuple[float, float] = (1.0, 1.0)  # 캡처 시 DPI 스케일

# 포커스된 창 정보
_focused_hwnd: int | None = None
_focused_rect: tuple[int, int, int, int] | None = None  # (left, top, right, bottom)
_focused_title: str | None = None


# ── DPI 스케일 보정 ───────────────────────────────────────────────────────────

def _get_capture_scale(
    img: "Image.Image",
    bbox: tuple[int, int, int, int] | None,
) -> tuple[float, float]:
    """
    캡처된 이미지 픽셀과 해당 화면 영역의 비율을 반환.
    bbox가 있으면 bbox 크기와 비교, 없으면 전체 화면과 비교.
    DPI 스케일이 걸려 있으면 1.0이 아닌 값이 나옴.
    """
    img_w, img_h = img.size
    if bbox:
        area_w = bbox[2] - bbox[0]
        area_h = bbox[3] - bbox[1]
    else:
        import pyautogui
        area_w, area_h = pyautogui.size()

    scale_x = img_w / area_w if area_w else 1.0
    scale_y = img_h / area_h if area_h else 1.0
    logging.info(
        f"[desktop_skill] capture scale: image=({img_w}x{img_h}) "
        f"area=({area_w}x{area_h}) scale=({scale_x:.3f}, {scale_y:.3f})"
    )
    return scale_x, scale_y


# ── 창 포커스 helpers ─────────────────────────────────────────────────────────

def _focus_window_by_keyword(keyword: str) -> str | None:
    """
    keyword를 포함하는 최상위 창을 찾아 포그라운드로 가져옵니다.
    성공 시 창 제목 반환, HWND와 RECT를 모듈 변수에 저장.
    """
    global _focused_hwnd, _focused_rect, _focused_title

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
        _focused_hwnd = None
        _focused_rect = None
        _focused_title = None
        return None

    hwnd = found_hwnd[0]
    SW_RESTORE = 9
    ctypes.windll.user32.ShowWindow(hwnd, SW_RESTORE)   # 최소화 복원
    ctypes.windll.user32.SetForegroundWindow(hwnd)       # 포그라운드

    # 창 영역 저장
    rect = ctypes.wintypes.RECT()
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    _focused_hwnd = hwnd
    _focused_rect = (rect.left, rect.top, rect.right, rect.bottom)
    _focused_title = found_title[0]

    logging.info(
        f"[desktop_skill] Window focused: hwnd={hwnd} "
        f"rect={_focused_rect} title={_focused_title!r}"
    )
    return _focused_title


# ── OCR + 오버레이 ────────────────────────────────────────────────────────────

def _render_overlay(
    raw_img: "Image.Image",
    element_map: dict,
    scale: tuple[float, float],
    highlight: int | None = None,
) -> str:
    """
    저장된 원본 이미지에 번호 마커를 오버레이해 base64 PNG로 반환합니다.
    highlight: 특별히 강조할 요소 번호 (빨간 십자선 + 좌표 표시)
    """
    scale_x, scale_y = scale
    img_w, img_h = raw_img.size
    img_rgba = raw_img.convert("RGBA")
    overlay = Image.new("RGBA", raw_img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    try:
        font = ImageFont.truetype("arial.ttf", 13)
        font_hl = ImageFont.truetype("arial.ttf", 15)
    except Exception:
        font = ImageFont.load_default()
        font_hl = font

    for i, el in element_map.items():
        # 오버레이는 이미지 내 좌표로 그림
        ix = el.get("img_x", el["x"])
        iy = el.get("img_y", el["y"])

        if i == highlight:
            # 빨간 십자선: 클릭할 정확한 위치를 이미지 전체에 표시
            cross_color = (255, 40, 40, 180)
            draw.line([(ix, 0), (ix, img_h)], fill=cross_color, width=2)
            draw.line([(0, iy), (img_w, iy)], fill=cross_color, width=2)
            # 강조 원
            r = 16
            draw.ellipse([ix - r, iy - r, ix + r, iy + r],
                         fill=(30, 200, 80, 230), outline=(255, 255, 255, 255), width=2)
            label = str(i)
            bbox = draw.textbbox((0, 0), label, font=font_hl)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            draw.text((ix - tw / 2, iy - th / 2), label,
                      fill=(255, 255, 255, 255), font=font_hl)
            # 화면 절대 좌표 표시
            coord_text = f"click→({el['x']},{el['y']})"
            draw.text((ix + r + 4, iy - 8), coord_text,
                      fill=(255, 40, 40, 230), font=font)
        else:
            r = 11
            draw.ellipse([ix - r, iy - r, ix + r, iy + r],
                         fill=(255, 80, 0, 180))
            label = str(i)
            bbox = draw.textbbox((0, 0), label, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            draw.text((ix - tw / 2, iy - th / 2), label,
                      fill=(255, 255, 255, 255), font=font)

    combined = Image.alpha_composite(img_rgba, overlay).convert("RGB")
    buf = io.BytesIO()
    combined.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _build_annotated_screenshot() -> tuple[str, dict, str]:
    """
    포커스된 창 영역만 캡처하고 OCR로 텍스트를 감지해 번호 마커를 오버레이합니다.
    _focused_rect가 없으면 전체 화면을 캡처합니다.

    반환: (base64 PNG, element_map, ocr_status 메시지)
    element_map의 좌표는 화면 절대 좌표 (pyautogui.click에 직접 사용 가능).
    """
    global _last_raw_img, _last_scale, _focused_rect, _focused_hwnd

    # ── 포커스 창 RECT 갱신 (창이 이동했을 수 있으므로) ──────────────────────
    offset_x, offset_y = 0, 0
    bbox = None
    if _focused_hwnd is not None:
        rect = ctypes.wintypes.RECT()
        if ctypes.windll.user32.GetWindowRect(_focused_hwnd, ctypes.byref(rect)):
            _focused_rect = (rect.left, rect.top, rect.right, rect.bottom)
            bbox = _focused_rect
            offset_x, offset_y = rect.left, rect.top
            logging.info(f"[desktop_skill] Capturing window rect: {_focused_rect}")

    # ── 캡처 ─────────────────────────────────────────────────────────────────
    if bbox:
        img = ImageGrab.grab(bbox=bbox)
    else:
        img = ImageGrab.grab()
    _last_raw_img = img.copy()

    scale_x, scale_y = _get_capture_scale(img, bbox)
    _last_scale = (scale_x, scale_y)
    logging.info(f"[desktop_skill] Captured image: {img.size}, bbox={bbox}, offset=({offset_x},{offset_y})")

    elements: list[dict] = []
    ocr_status = ""

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
            if text and conf > 40 and w > 5 and h > 5:
                # 이미지 내 상대 좌표 (오버레이 그리기용)
                img_cx = data["left"][i] + w // 2
                img_cy = data["top"][i] + h // 2
                # 화면 절대 좌표 (pyautogui 클릭용)
                screen_x = int(img_cx / scale_x) + offset_x
                screen_y = int(img_cy / scale_y) + offset_y
                elements.append({
                    "text": text,
                    "screen_x": screen_x,
                    "screen_y": screen_y,
                    "img_x": img_cx,
                    "img_y": img_cy,
                })
        ocr_status = f"OCR 감지 완료: {len(elements)}개 텍스트 요소"
        logging.info(f"[desktop_skill] {ocr_status}")
    except ImportError:
        ocr_status = "⚠ pytesseract 미설치 — pip install pytesseract 필요"
        logging.error(f"[desktop_skill] {ocr_status}")
    except Exception as e:
        ocr_status = f"⚠ OCR 실패: {e}"
        logging.error(f"[desktop_skill] {ocr_status}")

    # element_map: "x","y" = 화면 절대 좌표 / "img_x","img_y" = 이미지 내 좌표
    element_map: dict[int, dict] = {
        i: {
            "x": el["screen_x"], "y": el["screen_y"],
            "img_x": el["img_x"], "img_y": el["img_y"],
            "text": el["text"],
        }
        for i, el in enumerate(elements, start=1)
    }

    # 오버레이 렌더링 — 이미지 내 좌표 사용
    b64 = _render_overlay(img, element_map, (scale_x, scale_y))
    return b64, element_map, ocr_status


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
                rect_msg = f" 영역: {_focused_rect}" if _focused_rect else ""
                return {
                    "status": "success",
                    "window_title": title,
                    "window_rect": _focused_rect,
                    "message": f"'{title}' 창을 포그라운드로 가져왔습니다.{rect_msg} 이제 desktop_screenshot을 실행하세요.",
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
            b64, _element_map, ocr_status = await loop.run_in_executor(
                None, _build_annotated_screenshot
            )

            elements_summary = {str(n): info["text"] for n, info in _element_map.items()}
            window_info = f"창: {_focused_title!r}" if _focused_title else "전체 화면"
            logging.info(
                f"[desktop_skill] Screenshot ready ({window_info}), "
                f"{len(_element_map)} elements annotated"
            )
            return {
                "status": "success",
                "window": window_info,
                "ocr_status": ocr_status,
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
        global _element_map, _last_raw_img, _last_scale
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

            x, y = int(el["x"]), int(el["y"])
            loop = asyncio.get_event_loop()

            # ── 클릭 전: 타깃 강조 이미지 생성 (저장된 원본 재활용, OCR 불필요) ──
            before_b64: str | None = None
            if _last_raw_img is not None:
                before_b64 = await loop.run_in_executor(
                    None,
                    lambda: _render_overlay(_last_raw_img, _element_map, _last_scale, highlight=number),
                )
                logging.info(f"[desktop_skill] Before-click preview rendered (element {number})")

            # ── 클릭 실행 ────────────────────────────────────────────────────
            logging.info(f"[desktop_skill] Clicking element {number}: '{el['text']}' at ({x}, {y})")
            diag = await loop.run_in_executor(None, lambda: _do_click(x, y))
            await asyncio.sleep(0.6)  # UI 반응 대기

            # ── 클릭 후: 새 스크린샷 캡처 + element_map 갱신 ─────────────────
            after_b64, new_map, _ = await loop.run_in_executor(None, _build_annotated_screenshot)
            _element_map = new_map
            logging.info(f"[desktop_skill] After-click screenshot captured ({len(new_map)} elements)")

            result: dict = {
                "status": "success",
                "message": (
                    f"요소 {number} ('{el['text']}') 클릭 — "
                    f"목표=({x},{y}) 커서결과=({diag['cursor_at'][0]},{diag['cursor_at'][1]})"
                ),
                "x": x,
                "y": y,
                "cursor_at": diag["cursor_at"],
                "elements": {str(n): info["text"] for n, info in new_map.items()},
            }
            # 이미지는 orchestrator가 images_base64 리스트로 처리
            images: list[str] = []
            if before_b64:
                images.append(before_b64)
            images.append(after_b64)
            result["images_base64"] = images
            return result

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
        logging.info(f"[desktop_skill] desktop_click_xy: ({x}, {y}) double={double_click}")
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None, lambda: _do_click(int(x), int(y), double=double_click)
            )
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

    async def run(self, text: str, press_enter: bool = False, **kwargs) -> dict:  # noqa: E501
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
