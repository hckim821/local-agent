import asyncio
import logging
from .skill_base import SkillBase
from .os_skill import _paste_text, _enum_visible_window_titles, _poll_for_window

_EES_APP_NAME = "EES UI"
_PNP_BUTTON = "PnP Desktop 실행"
_LAUNCH_TIMEOUT = 15.0   # seconds to wait for EES UI window
_BUTTON_TIMEOUT = 10.0   # seconds to wait for button to become clickable


async def _find_and_click_button(window_keyword: str, button_text: str) -> str | None:
    """
    Windows UI Automation으로 버튼을 찾아 클릭합니다.
    성공 시 버튼 텍스트 반환, 실패 시 None 반환.
    """
    try:
        # pywinauto UIA backend — works with Win32, WPF, WinForms, etc.
        from pywinauto import Desktop
        from pywinauto.findwindows import ElementNotFoundError

        # Find the target window (partial title match)
        desktop = Desktop(backend="uia")
        target_win = None

        for win in desktop.windows():
            try:
                title = win.window_text()
                if window_keyword.lower() in title.lower():
                    target_win = win
                    break
            except Exception:
                continue

        if target_win is None:
            return None

        # Bring window to foreground
        try:
            target_win.set_focus()
            await asyncio.sleep(0.5)
        except Exception:
            pass

        # Search for button recursively (depth-first)
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
            logging.warning(
                f"[ees_skill] Button {button_text!r} not found in {window_keyword!r}"
            )
            return None

        button_label = button.window_text()
        logging.info(f"[ees_skill] Clicking button: {button_label!r}")
        button.click_input()
        return button_label

    except Exception as e:
        logging.error(f"[ees_skill] UI Automation error: {e}", exc_info=True)
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

        # ── Step 2: PnP Desktop 실행 버튼 클릭 ────────────────────────────────
        # Give the app a moment to fully render its UI
        await asyncio.sleep(2.0)

        logging.info(f"[ees_skill] Looking for button: {_PNP_BUTTON!r}")
        clicked = await _find_and_click_button(_EES_APP_NAME, _PNP_BUTTON)

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
