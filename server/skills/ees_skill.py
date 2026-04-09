import asyncio
import logging
from .skill_base import SkillBase
from .os_skill import _paste_text, _enum_visible_window_titles, _poll_for_window

_EES_APP_NAME = "EES UI"
_PNP_BUTTON = "PnP Desktop 실행"
_LAUNCH_TIMEOUT = 15.0   # seconds to wait for EES UI window
_BUTTON_TIMEOUT = 10.0   # seconds to wait for button to become clickable


def _try_find_and_click_button(window_keyword: str, button_text: str) -> str | None:
    """
    Windows UI Automation으로 버튼을 한 번 탐색하여 클릭합니다.
    성공 시 버튼 텍스트 반환, 실패(미발견 포함) 시 None 반환.
    """
    try:
        from pywinauto import Desktop

        desktop = Desktop(backend="uia")
        target_win = None

        for win in desktop.windows():
            try:
                if window_keyword.lower() in win.window_text().lower():
                    target_win = win
                    break
            except Exception:
                continue

        if target_win is None:
            return None

        try:
            target_win.set_focus()
        except Exception:
            pass

        def _find_button(element, keyword: str, depth: int = 0):
            if depth > 8:
                return None
            try:
                text = element.window_text()
                ctrl_type = element.element_info.control_type
                if keyword.lower() in text.lower() and ctrl_type in ("Button", "Custom"):
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

        label = button.window_text()
        button.click_input()
        logging.info(f"[ees_skill] Clicked: {label!r}")
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
