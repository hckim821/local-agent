import asyncio
import ctypes
import ctypes.wintypes
import logging
from .skill_base import SkillBase


# ── Windows API helpers ───────────────────────────────────────────────────────

def _paste_text(text: str) -> None:
    """
    Copy text to clipboard via Windows API and paste with Ctrl+V.
    Works with Korean and all Unicode characters (unlike pyautogui.typewrite).
    """
    import pyperclip
    pyperclip.copy(text)

    import pyautogui
    pyautogui.hotkey("ctrl", "v")


def _enum_visible_window_titles() -> list[str]:
    """Return titles of all currently visible top-level windows."""
    titles: list[str] = []

    EnumWindowsProc = ctypes.WINFUNCTYPE(
        ctypes.wintypes.BOOL,
        ctypes.wintypes.HWND,
        ctypes.wintypes.LPARAM,
    )

    def _callback(hwnd: int, _: int) -> bool:
        if ctypes.windll.user32.IsWindowVisible(hwnd):
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
                titles.append(buf.value)
        return True

    ctypes.windll.user32.EnumWindows(EnumWindowsProc(_callback), 0)
    return titles


def _window_appeared(keyword: str, before: list[str]) -> str | None:
    """
    Return the title of a window that contains `keyword` (case-insensitive),
    prioritising windows that are new since `before` was captured.
    """
    keyword_lower = keyword.lower()
    after = _enum_visible_window_titles()
    new_titles = set(after) - set(before)

    for title in new_titles:
        if keyword_lower in title.lower():
            return title

    # Fallback: any existing visible window matching keyword
    for title in after:
        if keyword_lower in title.lower():
            return title

    return None


async def _poll_for_window(
    keyword: str,
    before: list[str],
    timeout: float = 10.0,
    interval: float = 0.5,
) -> str | None:
    """
    Poll every `interval` seconds until a window matching `keyword` appears
    or `timeout` seconds have elapsed.
    """
    elapsed = 0.0
    while elapsed < timeout:
        result = _window_appeared(keyword, before)
        if result:
            return result
        await asyncio.sleep(interval)
        elapsed += interval
    return None


# ── Skills ────────────────────────────────────────────────────────────────────

class RunApplicationSkill(SkillBase):
    name = "run_application"
    description = "Windows 검색창을 통해 애플리케이션을 실행합니다."
    parameters = {
        "type": "object",
        "properties": {
            "app_name": {
                "type": "string",
                "description": "실행할 애플리케이션 이름 (한글 가능)",
            }
        },
        "required": ["app_name"],
    }

    async def run(self, app_name: str, **kwargs) -> dict:
        import pyautogui

        logging.info(f"[os_skill] run_application: {app_name!r}")

        try:
            # Snapshot open windows before launch
            windows_before = _enum_visible_window_titles()

            # Open Windows Search
            pyautogui.press("win")
            await asyncio.sleep(1.0)

            # Clear any stale search text, then paste app_name via clipboard
            # (typewrite breaks Korean — clipboard paste preserves all Unicode)
            pyautogui.hotkey("ctrl", "a")
            await asyncio.sleep(0.2)
            _paste_text(app_name)
            await asyncio.sleep(1.5)

            # Launch the top search result
            pyautogui.press("enter")

            # Poll until the app window appears (up to 10 seconds)
            logging.info(f"[os_skill] Waiting for window: {app_name!r}")
            matched_title = await _poll_for_window(app_name, windows_before)
            if matched_title:
                logging.info(f"[os_skill] Window found: {matched_title!r}")
                return {
                    "status": "success",
                    "app_name": app_name,
                    "window_title": matched_title,
                    "message": f"'{app_name}' 실행 성공 (창: {matched_title})",
                }
            else:
                logging.warning(
                    f"[os_skill] No window found for {app_name!r}. "
                    f"Open windows: {_enum_visible_window_titles()}"
                )
                return {
                    "status": "not_found",
                    "app_name": app_name,
                    "message": (
                        f"'{app_name}'을(를) 검색했지만 실행된 창을 찾지 못했습니다. "
                        "앱 이름을 확인하거나 직접 실행해 주세요."
                    ),
                }

        except Exception as e:
            logging.error(f"[os_skill] run_application failed: {e}", exc_info=True)
            return {
                "status": "error",
                "app_name": app_name,
                "message": f"앱 실행 중 오류: {e}",
            }
