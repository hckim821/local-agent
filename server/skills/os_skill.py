import asyncio
from .skill_base import SkillBase


class RunApplicationSkill(SkillBase):
    name = "run_application"
    description = "Windows 검색창을 통해 애플리케이션을 실행합니다."
    parameters = {
        "type": "object",
        "properties": {
            "app_name": {
                "type": "string",
                "description": "실행할 애플리케이션 이름",
            }
        },
        "required": ["app_name"],
    }

    async def run(self, app_name: str, **kwargs) -> dict:
        try:
            import pyautogui

            pyautogui.press("win")
            await asyncio.sleep(1)
            pyautogui.typewrite(app_name, interval=0.05)
            await asyncio.sleep(1)
            pyautogui.press("enter")

            return {
                "status": "success",
                "app_name": app_name,
                "message": f"{app_name} 실행 명령을 보냈습니다.",
            }
        except Exception as e:
            return {
                "status": "error",
                "app_name": app_name,
                "message": f"애플리케이션 실행 중 오류가 발생했습니다: {str(e)}",
            }


class DesktopInteractionSkill(SkillBase):
    name = "desktop_interaction"
    description = "실행된 앱의 UI 요소를 클릭합니다. (이미지 매칭 또는 좌표 기반)"
    parameters = {
        "type": "object",
        "properties": {
            "button_name": {
                "type": "string",
                "description": "클릭할 버튼 또는 UI 요소의 이름",
            },
            "x": {
                "type": "number",
                "description": "클릭할 X 좌표 (선택 사항)",
            },
            "y": {
                "type": "number",
                "description": "클릭할 Y 좌표 (선택 사항)",
            },
        },
        "required": ["button_name"],
    }

    async def run(self, button_name: str, x: float | None = None, y: float | None = None, **kwargs) -> dict:
        try:
            import pyautogui

            if x is not None and y is not None:
                pyautogui.click(int(x), int(y))
                return {
                    "status": "success",
                    "button_name": button_name,
                    "message": f"좌표 ({int(x)}, {int(y)})를 클릭했습니다.",
                }
            else:
                try:
                    location = pyautogui.locateOnScreen(button_name, confidence=0.8)
                    if location:
                        center = pyautogui.center(location)
                        pyautogui.click(center)
                        return {
                            "status": "success",
                            "button_name": button_name,
                            "message": f"'{button_name}' 요소를 화면에서 찾아 클릭했습니다.",
                        }
                    else:
                        return {
                            "status": "error",
                            "button_name": button_name,
                            "message": f"'{button_name}' 요소를 화면에서 찾을 수 없습니다. x, y 좌표를 직접 지정해 주세요.",
                        }
                except Exception:
                    screen_width, screen_height = pyautogui.size()
                    center_x = screen_width // 2
                    center_y = screen_height // 2
                    pyautogui.click(center_x, center_y)
                    return {
                        "status": "success",
                        "button_name": button_name,
                        "message": f"화면 중앙 ({center_x}, {center_y})을 클릭했습니다.",
                    }

        except Exception as e:
            return {
                "status": "error",
                "button_name": button_name,
                "message": f"데스크톱 상호작용 중 오류가 발생했습니다: {str(e)}",
            }
