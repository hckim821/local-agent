import asyncio
import ctypes
import ctypes.wintypes
import logging
from .skill_base import SkillBase
from .os_skill import _paste_text, _enum_visible_window_titles, _poll_for_window

_EES_APP_NAME = "EES UI"
_PNP_BUTTON = "PnP Desktop 실행"
_LAUNCH_TIMEOUT = 15.0
_BUTTON_TIMEOUT = 10.0


def _find_hwnd_by_keyword(keyword: str) -> int | None:
    """
    ctypes EnumWindows로 keyword를 포함하는 가시 창의 HWND를 반환합니다.
    pywinauto window_text()와 달리 GetWindowTextW는 대부분의 앱에서 정상 동작합니다.
    """
    found: list[int] = []
    keyword_lower = keyword.lower()

    EnumProc = ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)

    def _cb(hwnd: int, _: int) -> bool:
        if not ctypes.windll.user32.IsWindowVisible(hwnd):
            return True
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
        if keyword_lower in buf.value.lower():
            found.append(hwnd)
            return False  # 첫 번째 매칭에서 중단
        return True

    ctypes.windll.user32.EnumWindows(EnumProc(_cb), 0)
    return found[0] if found else None


def _try_find_and_click_button(window_keyword: str, button_text: str) -> str | None:
    """
    ctypes로 HWND를 찾은 뒤 pywinauto UIA 백엔드로 연결하여 버튼을 클릭합니다.
    window_text()가 None을 반환하는 앱도 핸들 기반 연결로 우회합니다.
    """
    try:
        hwnd = _find_hwnd_by_keyword(window_keyword)
        if hwnd is None:
            logging.debug(f"[ees_skill] HWND not found for {window_keyword!r}")
            return None

        # GetWindowText로 실제 타이틀 확인
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
        actual_title = buf.value
        logging.info(f"[ees_skill] Found window HWND={hwnd} title={actual_title!r}")

        from pywinauto import Application

        # handle= 로 연결하면 window_text() 의존 없이 동작
        app = Application(backend="uia").connect(handle=hwnd)
        target_win = app.top_window()

        try:
            target_win.set_focus()
        except Exception:
            pass

        def _find_button(element, keyword: str, depth: int = 0):
            if depth > 8:
                return None
            try:
                # element_info.name 이 window_text()보다 UIA에서 더 안정적
                name = element.element_info.name or element.window_text() or ""
                ctrl_type = element.element_info.control_type
                if keyword.lower() in name.lower() and ctrl_type in ("Button", "Custom"):
                    return element
            except Exception:
                pass
            try:
                for child in element.children():
                    result = _find_button(child, keyword, depth + 1)
                    if result is not None:
                        return result
            except Exception:
                pass
            return None

        button = _find_button(target_win, button_text)
        if button is None:
            return None

        label = button.element_info.name or button.window_text()
        button.click_input()
        logging.info(f"[ees_skill] Clicked button: {label!r}")
        return label

    except Exception as e:
        logging.debug(f"[ees_skill] _try_find_and_click_button error: {e}")
        return None


async def _poll_for_button(
    window_keyword: str,
    button_text: str,
    timeout: float = 10.0,
    interval: float = 0.5,
) -> str | None:
    """
    버튼이 나타날 때까지 interval마다 재시도합니다.
    앱이 느리게 로딩되어 버튼이 늦게 렌더링되는 경우에도 안정적으로 동작합니다.
    """
    elapsed = 0.0
    attempt = 0
    while elapsed < timeout:
        attempt += 1
        logging.info(
            f"[ees_skill] Button poll #{attempt} ({elapsed:.1f}s / {timeout}s)"
        )
        result = _try_find_and_click_button(window_keyword, button_text)
        if result is not None:
            return result
        await asyncio.sleep(interval)
        elapsed += interval
    return None


class RunEESSkill(SkillBase):
    name = "run_ees"
    description = (
        "EES UI 애플리케이션을 실행한 뒤 "
        "'PnP Desktop 실행' 버튼을 자동으로 클릭합니다."
    )
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    async def run(self, **kwargs) -> dict:
        import pyautogui

        logging.info("[ees_skill] run_ees started")

        # ── Step 1: EES UI 실행 ────────────────────────────────────────────────
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

        # ── Step 2: PnP Desktop 실행 버튼 클릭 (폴링) ────────────────────────
        logging.info(f"[ees_skill] Polling for button: {_PNP_BUTTON!r}")
        clicked = await _poll_for_button(
            _EES_APP_NAME, _PNP_BUTTON, timeout=_BUTTON_TIMEOUT, interval=0.5
        )

        if clicked:
            return {
                "status": "success",
                "message": (
                    f"EES UI를 실행하고 '{clicked}' 버튼을 클릭했습니다."
                ),
            }
        else:
            return {
                "status": "not_found",
                "step": "button_click",
                "message": (
                    f"EES UI는 열렸지만 '{_PNP_BUTTON}' 버튼을 찾지 못했습니다. "
                    "버튼 이름이 정확한지 확인하거나 x, y 좌표를 desktop_interaction 스킬로 직접 지정해 주세요."
                ),
            }
