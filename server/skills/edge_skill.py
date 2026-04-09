"""
Edge 브라우저 스킬 모음

Playwright로 Edge를 직접 실행해 제어합니다.
브라우저는 스킬 호출 후에도 열린 상태를 유지합니다.
"""

import asyncio
import logging
import os
import base64
import io
from pathlib import Path
from .skill_base import SkillBase

# ── Edge 실행 파일 경로 후보 ───────────────────────────────────────────────────
_EDGE_CANDIDATES = [
    Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
    / "Microsoft" / "Edge" / "Application" / "msedge.exe",
    Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
    / "Microsoft" / "Edge" / "Application" / "msedge.exe",
]

# 모듈 수준에서 브라우저·페이지 인스턴스를 유지 (열린 상태 보존)
_browser = None
_page = None
_playwright = None

# 마지막 스크린샷의 요소 맵: {번호: {"x": float, "y": float, "text": str}}
_element_map: dict[int, dict] = {}


def _find_edge() -> str | None:
    env = os.environ.get("EDGE_EXECUTABLE_PATH")
    if env and Path(env).exists():
        return env
    for c in _EDGE_CANDIDATES:
        if c.exists():
            return str(c)
    return None


async def _ensure_browser(url: str | None = None) -> tuple:
    """
    브라우저가 이미 열려 있으면 재사용하고, url이 있으면 해당 페이지로 이동합니다.
    열려 있지 않으면 새 Edge 인스턴스를 실행합니다.
    """
    global _browser, _page, _playwright

    # 기존 브라우저가 살아있으면 재사용
    if _browser is not None:
        try:
            _ = _browser.is_connected()
            if url:
                logging.info(f"[edge_skill] Reusing browser, navigating to {url}")
                await _page.goto(url, wait_until="load", timeout=30000)
            return _browser, _page
        except Exception:
            _browser = None
            _page = None
            _playwright = None

    edge_path = _find_edge()
    if edge_path is None:
        raise RuntimeError(
            "msedge.exe를 찾을 수 없습니다. "
            "EDGE_EXECUTABLE_PATH 환경변수로 경로를 지정하거나 Edge를 설치하세요."
        )

    from playwright.async_api import async_playwright as _ap

    _playwright = await _ap().__aenter__()
    _browser = await _playwright.chromium.launch(
        executable_path=edge_path,
        headless=False,
        args=["--start-maximized"],
    )
    ctx = await _browser.new_context(no_viewport=True)
    _page = await ctx.new_page()
    logging.info("[edge_skill] Edge launched via Playwright")

    if url:
        logging.info(f"[edge_skill] Navigating to {url}")
        await _page.goto(url, wait_until="load", timeout=30000)

    return _browser, _page


async def _capture_annotated_screenshot(page) -> tuple[str, dict]:
    """
    스크린샷을 찍고 클릭 가능한 요소에 번호 마커를 오버레이합니다.
    (base64 이미지, 요소맵) 튜플 반환.
    """
    from PIL import Image, ImageDraw, ImageFont

    # 요소 목록 추출: 링크·버튼·input·role=button
    elements = await page.evaluate("""() => {
        const selectors = 'a, button, input, [role="button"], [role="link"], [role="menuitem"], [role="tab"]';
        const viewport = { w: window.innerWidth, h: window.innerHeight };
        return Array.from(document.querySelectorAll(selectors))
            .map(el => {
                const r = el.getBoundingClientRect();
                const text = (el.innerText || el.value || el.getAttribute('aria-label') || el.getAttribute('title') || '').trim().slice(0, 40);
                return { x: r.left + r.width/2, y: r.top + r.height/2, w: r.width, h: r.height, text };
            })
            .filter(e => e.w > 0 && e.h > 0 && e.x >= 0 && e.y >= 0 && e.x <= viewport.w && e.y <= viewport.h);
    }""")

    # 스크린샷 (원본)
    png_bytes = await page.screenshot(full_page=False)
    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    try:
        font = ImageFont.truetype("arial.ttf", 13)
        font_small = font
    except Exception:
        font = ImageFont.load_default()
        font_small = font

    element_map: dict[int, dict] = {}
    for i, el in enumerate(elements, start=1):
        x, y = el["x"], el["y"]
        r = 11
        # 반투명 원 배경
        draw.ellipse([x - r, y - r, x + r, y + r], fill=(255, 80, 0, 200))
        # 번호 텍스트
        label = str(i)
        bbox = draw.textbbox((0, 0), label, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text((x - tw / 2, y - th / 2), label, fill=(255, 255, 255, 255), font=font)
        element_map[i] = {"x": x, "y": y, "text": el["text"]}

    combined = Image.alpha_composite(img, overlay).convert("RGB")
    buf = io.BytesIO()
    combined.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()

    return b64, element_map


# ── 스킬 1: Edge 열고 URL 이동 ───────────────────────────────────────────────

class OpenEdgeSkill(SkillBase):
    name = "open_edge"
    description = (
        "Edge 브라우저를 열고 지정한 URL로 이동합니다. "
        "브라우저는 닫지 않고 유지합니다."
    )
    parameters = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "이동할 URL (예: https://example.com)",
            },
        },
        "required": ["url"],
    }

    async def run(self, url: str, **kwargs) -> dict:
        logging.info(f"[edge_skill] open_edge: url={url!r}")
        try:
            _, page = await _ensure_browser(url)
            title = await page.title()
            current_url = page.url
            logging.info(f"[edge_skill] Navigated. title={title!r} url={current_url!r}")
            return {
                "status": "success",
                "url": current_url,
                "title": title,
                "message": f"Edge에서 '{title}' 페이지를 열었습니다. ({current_url})",
            }
        except Exception as e:
            logging.error(f"[edge_skill] open_edge failed: {e}", exc_info=True)
            return {"status": "error", "message": f"Edge 실행 오류: {e}"}


# ── 스킬 2: 스크린샷 + 요소 번호 오버레이 ───────────────────────────────────

class EdgeScreenshotSkill(SkillBase):
    name = "edge_screenshot"
    description = (
        "현재 열린 Edge 브라우저의 스크린샷을 찍습니다. "
        "클릭 가능한 요소(링크·버튼 등)에 번호 마커를 표시하고, "
        "번호와 요소 텍스트 목록을 함께 반환합니다. "
        "클릭이 필요할 때는 반드시 이 스킬로 번호를 확인한 뒤 edge_click_element를 사용하세요."
    )
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    async def run(self, **kwargs) -> dict:
        global _element_map
        logging.info("[edge_skill] edge_screenshot called")
        try:
            _, page = await _ensure_browser()
            b64, _element_map = await _capture_annotated_screenshot(page)
            title = await page.title()
            logging.info(f"[edge_skill] Screenshot captured, {len(_element_map)} elements annotated")

            # LLM에게 전달할 요소 목록 (텍스트)
            elements_summary = {
                str(n): info["text"] or "(no text)"
                for n, info in _element_map.items()
            }
            return {
                "status": "success",
                "title": title,
                "url": page.url,
                "elements": elements_summary,
                "image_base64": b64,
            }
        except Exception as e:
            logging.error(f"[edge_skill] edge_screenshot failed: {e}", exc_info=True)
            return {"status": "error", "message": f"스크린샷 오류: {e}"}


# ── 스킬 3: 번호로 요소 클릭 ────────────────────────────────────────────────

class EdgeClickElementSkill(SkillBase):
    name = "edge_click_element"
    description = (
        "edge_screenshot에서 표시된 번호로 요소를 클릭합니다. "
        "반드시 edge_screenshot을 먼저 실행해 번호를 확인한 뒤 사용하세요."
    )
    parameters = {
        "type": "object",
        "properties": {
            "number": {
                "type": "integer",
                "description": "클릭할 요소의 번호 (edge_screenshot 이미지에 표시된 번호)",
            },
        },
        "required": ["number"],
    }

    async def run(self, number: int, **kwargs) -> dict:
        global _element_map
        logging.info(f"[edge_skill] edge_click_element: number={number}")
        try:
            if not _element_map:
                return {"status": "error", "message": "먼저 edge_screenshot을 실행해 요소 목록을 확인하세요."}

            el = _element_map.get(number)
            if el is None:
                return {
                    "status": "error",
                    "message": f"번호 {number}에 해당하는 요소가 없습니다. 유효 범위: 1~{max(_element_map.keys())}",
                }

            _, page = await _ensure_browser()
            await page.mouse.click(el["x"], el["y"])
            await asyncio.sleep(0.5)
            logging.info(f"[edge_skill] Clicked element {number}: '{el['text']}' at ({el['x']:.0f}, {el['y']:.0f})")
            return {
                "status": "success",
                "message": f"요소 {number} ('{el['text']}') 클릭 완료",
                "x": el["x"],
                "y": el["y"],
            }
        except Exception as e:
            logging.error(f"[edge_skill] edge_click_element failed: {e}", exc_info=True)
            return {"status": "error", "message": f"클릭 오류: {e}"}


# ── 스킬 4: 좌표 직접 클릭 (fallback) ───────────────────────────────────────

class EdgeClickSkill(SkillBase):
    name = "edge_click"
    description = (
        "화면의 특정 좌표를 직접 클릭합니다. "
        "가능하면 edge_click_element를 사용하고, "
        "번호 목록에 없는 위치를 클릭할 때만 이 스킬을 사용하세요."
    )
    parameters = {
        "type": "object",
        "properties": {
            "x": {"type": "number", "description": "클릭할 X 좌표 (픽셀)"},
            "y": {"type": "number", "description": "클릭할 Y 좌표 (픽셀)"},
        },
        "required": ["x", "y"],
    }

    async def run(self, x: float, y: float, **kwargs) -> dict:
        logging.info(f"[edge_skill] edge_click: ({x}, {y})")
        try:
            _, page = await _ensure_browser()
            await page.mouse.click(x, y)
            await asyncio.sleep(0.5)
            return {
                "status": "success",
                "message": f"좌표 ({int(x)}, {int(y)}) 클릭 완료",
            }
        except Exception as e:
            logging.error(f"[edge_skill] edge_click failed: {e}", exc_info=True)
            return {"status": "error", "message": f"클릭 오류: {e}"}


# ── 스킬 5: 텍스트 입력 ──────────────────────────────────────────────────────

class EdgeTypeSkill(SkillBase):
    name = "edge_type"
    description = (
        "현재 포커스된 Edge 입력 필드에 텍스트를 입력합니다. "
        "edge_click_element로 입력란을 클릭한 뒤 사용합니다."
    )
    parameters = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "입력할 텍스트"},
        },
        "required": ["text"],
    }

    async def run(self, text: str, **kwargs) -> dict:
        logging.info(f"[edge_skill] edge_type: text={text!r}")
        try:
            _, page = await _ensure_browser()
            await page.keyboard.type(text)
            return {
                "status": "success",
                "message": f"텍스트 입력 완료: {text!r}",
            }
        except Exception as e:
            logging.error(f"[edge_skill] edge_type failed: {e}", exc_info=True)
            return {"status": "error", "message": f"텍스트 입력 오류: {e}"}
