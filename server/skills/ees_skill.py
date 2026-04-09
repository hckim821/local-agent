import asyncio
import ctypes
import ctypes.wintypes
import logging
from .skill_base import SkillBase
from .os_skill import _paste_text, _enum_visible_window_titles, _poll_for_window

_EES_APP_NAME = "EES UI"
_PNP_BUTTON   = "PnP Desktop 실행"
_LAUNCH_TIMEOUT = 15.0
_BUTTON_TIMEOUT = 15.0
_BUTTON_INTERVAL = 1.0   # 탐색 1회에 수초 걸릴 수 있으므로 여유 있게 설정


# ── ctypes helpers ────────────────────────────────────────────────────────────

def _find_hwnd_by_keyword(keyword: str) -> int | None:
    """GetWindowTextW로 keyword 포함 창의 HWND 반환 (pywinauto window_text() 우회)."""
    found: list[int] = []
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
            found.append(hwnd)
            return False
        return True

    ctypes.windll.user32.EnumWindows(EnumProc(_cb), 0)
    return found[0] if found else None


def _get_window_title(hwnd: int) -> str:
    n = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    ctypes.windll.user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def _find_child_hwnd_by_text(parent_hwnd: int, keyword: str) -> int | None:
    """
    EnumChildWindows(재귀 포함)로 keyword를 포함하는 자식 HWND 반환.
    Win32 네이티브 버튼에 즉시 동작 (수ms).
    """
    found: list[int] = []
    kw = keyword.lower()
    EnumProc = ctypes.WINFUNCTYPE(
        ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM
    )

    def _cb(hwnd: int, _: int) -> bool:
        n = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        if n == 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, n + 1)
        if kw in buf.value.lower():
            found.append(hwnd)
            return False
        return True

    ctypes.windll.user32.EnumChildWindows(parent_hwnd, EnumProc(_cb), 0)
    return found[0] if found else None


def _click_hwnd_center(hwnd: int) -> bool:
    """HWND의 화면 중심 좌표를 구해 pyautogui로 클릭합니다."""
    try:
        import pyautogui
        rect = ctypes.wintypes.RECT()
        ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
        cx = (rect.left + rect.right) // 2
        cy = (rect.top + rect.bottom) // 2
        pyautogui.click(cx, cy)
        logging.info(f"[ees_skill] Clicked via ctypes HWND at ({cx}, {cy})")
        return True
    except Exception as e:
        logging.debug(f"[ees_skill] _click_hwnd_center failed: {e}")
        return False


# ── pywinauto fallback (WPF / 커스텀 컨트롤) ──────────────────────────────────

def _uia_rect_click(hwnd: int, button_text: str) -> str | None:
    """
    pywinauto UIA 백엔드의 descendants() 로 전체 요소를 한 번에 가져와서
    rectangle() 좌표 기반 물리 클릭합니다.
    C# WPF 앱은 컨트롤별 HWND가 없으므로 click_input() 대신 pyautogui.click() 사용.
    """
    try:
        import pyautogui
        from pywinauto import Application

        app = Application(backend="uia").connect(handle=hwnd)
        win = app.top_window()
        try:
            win.set_focus()
        except Exception:
            pass

        kw = button_text.lower()

        # descendants()는 내부적으로 IUIAutomation::FindAll 단일 호출
        for elem in win.descendants():
            try:
                name = (elem.element_info.name or "").strip()
                if kw in name.lower():
                    rect = elem.rectangle()
                    cx = (rect.left + rect.right) // 2
                    cy = (rect.top + rect.bottom) // 2
                    pyautogui.click(cx, cy)
                    logging.info(f"[ees_skill] UIA rect-click: {name!r} at ({cx}, {cy})")
                    return name
            except Exception:
                continue

        return None

    except Exception as e:
        logging.debug(f"[ees_skill] _uia_rect_click error: {e}")
        return None


# ── 통합 탐색·클릭 함수 ───────────────────────────────────────────────────────

def _try_find_and_click_button(window_keyword: str, button_text: str) -> str | None:
    """
    1) ctypes EnumChildWindows + pyautogui  — Win32 / WinForms (수ms)
    2) UIA rectangle() + pyautogui.click()  — C# WPF / 커스텀 컨트롤 (수백ms)

    WPF는 컨트롤별 HWND가 없으므로 1단계가 실패해도
    2단계에서 UIA 좌표 기반 물리 클릭으로 처리합니다.
    """
    hwnd = _find_hwnd_by_keyword(window_keyword)
    if hwnd is None:
        logging.debug(f"[ees_skill] Window not found: {window_keyword!r}")
        return None

    title = _get_window_title(hwnd)
    logging.info(f"[ees_skill] Window HWND={hwnd} title={title!r}")

    # ── 1단계: Win32 child HWND 탐색 (WinForms 등) ───────────────
    child_hwnd = _find_child_hwnd_by_text(hwnd, button_text)
    if child_hwnd is not None:
        child_title = _get_window_title(child_hwnd)
        logging.info(f"[ees_skill] Win32 button HWND={child_hwnd} text={child_title!r}")
        if _click_hwnd_center(child_hwnd):
            return child_title

    # ── 2단계: UIA 좌표 기반 물리 클릭 (C# WPF 대응) ────────────
    logging.info("[ees_skill] Trying UIA rectangle-based click (WPF mode)...")
    return _uia_rect_click(hwnd, button_text)


# ── 폴링 ─────────────────────────────────────────────────────────────────────

async def _poll_for_button(
    window_keyword: str,
    button_text: str,
    timeout: float = _BUTTON_TIMEOUT,
    interval: float = _BUTTON_INTERVAL,
) -> str | None:
    elapsed = 0.0
    attempt = 0
    while elapsed < timeout:
        attempt += 1
        logging.info(f"[ees_skill] Button poll #{attempt} elapsed={elapsed:.1f}s")
        result = _try_find_and_click_button(window_keyword, button_text)
        if result is not None:
            return result
        await asyncio.sleep(interval)
        elapsed += interval
    return None


# ── Skill ─────────────────────────────────────────────────────────────────────

class RunEESSkill(SkillBase):
    name = "run_ees"
    description = (
        "EES UI 애플리케이션을 실행한 뒤 'PnP Desktop 실행' 버튼을 자동으로 클릭합니다."
    )
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    async def run(self, **kwargs) -> dict:
        import pyautogui

        logging.info("[ees_skill] run_ees started")

        # ── Step 1: EES UI 실행 ───────────────────────────────────
        windows_before = _enum_visible_window_titles()

        pyautogui.press("win")
        await asyncio.sleep(1.0)
        pyautogui.hotkey("ctrl", "a")
        await asyncio.sleep(0.2)
        _paste_text(_EES_APP_NAME)
        await asyncio.sleep(1.5)
        pyautogui.press("enter")

        logging.info(f"[ees_skill] Waiting for '{_EES_APP_NAME}' window...")
        ees_window = await _poll_for_window(
            _EES_APP_NAME, windows_before, timeout=_LAUNCH_TIMEOUT
        )

        if ees_window is None:
            return {
                "status": "error",
                "step": "launch",
                "message": (
                    f"'{_EES_APP_NAME}'을(를) 실행했지만 창이 열리지 않았습니다. "
                    "앱 이름을 확인하거나 수동으로 실행해 주세요."
                ),
            }

        logging.info(f"[ees_skill] EES UI opened: {ees_window!r}")

        # ── Step 2: 버튼 클릭 (폴링) ─────────────────────────────
        logging.info(f"[ees_skill] Polling for button: {_PNP_BUTTON!r}")
        clicked = await _poll_for_button(_EES_APP_NAME, _PNP_BUTTON)

        if clicked:
            return {
                "status": "success",
                "message": f"EES UI를 실행하고 '{clicked}' 버튼을 클릭했습니다.",
            }

        return {
            "status": "not_found",
            "step": "button_click",
            "message": (
                f"EES UI는 열렸지만 '{_PNP_BUTTON}' 버튼을 찾지 못했습니다. "
                "desktop_interaction 스킬로 x, y 좌표를 직접 지정하거나 "
                "버튼 텍스트(_PNP_BUTTON 상수)가 실제 앱 UI와 동일한지 확인해 주세요."
            ),
        }
