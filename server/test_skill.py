"""
스킬 직접 테스트 CLI

사용법:
  python test_skill.py                        # 등록된 스킬 목록
  python test_skill.py <skill_name>           # 파라미터 없이 실행
  python test_skill.py <skill_name> key=value # 파라미터 전달

예시:
  python test_skill.py run_ees
  python test_skill.py open_browser url=https://google.com
"""

import asyncio
import json
import logging
import sys
from pathlib import Path

# server/ 디렉터리를 경로에 추가
sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s  %(message)s",
)


def parse_args(raw: list[str]) -> dict:
    """key=value 형태의 인자를 dict로 변환. JSON 값도 지원."""
    kwargs = {}
    for item in raw:
        if "=" not in item:
            print(f"[warn] 무시된 인자: {item!r}  (key=value 형식이어야 합니다)")
            continue
        k, _, v = item.partition("=")
        # JSON 파싱 시도 (숫자, bool, 리스트, dict 지원)
        try:
            kwargs[k] = json.loads(v)
        except json.JSONDecodeError:
            kwargs[k] = v
    return kwargs


async def main():
    from skills import skill_registry

    skill_registry.load_skills()

    if len(sys.argv) < 2:
        skills = skill_registry.list_all()
        print(f"\n등록된 스킬 ({len(skills)}개):\n")
        for s in skills:
            params = list(s["parameters"].get("properties", {}).keys())
            param_str = ", ".join(params) if params else "(없음)"
            print(f"  {s['name']:<30} {s['description'][:60]}")
            print(f"  {'':30} params: {param_str}\n")
        print("사용법: python test_skill.py <skill_name> [key=value ...]")
        return

    skill_name = sys.argv[1]
    kwargs = parse_args(sys.argv[2:])

    skill = skill_registry.get(skill_name)
    if skill is None:
        print(f"\n[error] '{skill_name}' 스킬을 찾을 수 없습니다.")
        print("등록된 스킬 목록은 인자 없이 실행하면 확인할 수 있습니다.")
        sys.exit(1)

    print(f"\n▶  {skill_name} 실행 중...")
    if kwargs:
        print(f"   params: {json.dumps(kwargs, ensure_ascii=False)}")
    print()

    result = await skill.run(**kwargs)

    # 스크린샷 결과면 이미지 뷰어로 표시 후 base64는 출력 생략
    if "image_base64" in result:
        import base64 as _b64
        import io
        from PIL import Image

        data = _b64.b64decode(result.pop("image_base64"))
        img = Image.open(io.BytesIO(data))
        img.show(title="edge_screenshot")
        print("\n[이미지 뷰어로 스크린샷을 표시했습니다]")

    print("\n── 결과 ─────────────────────────────────────────")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("─────────────────────────────────────────────────\n")


if __name__ == "__main__":
    asyncio.run(main())
