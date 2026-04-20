"""위키 스킬 동적 로드/언로드 헬퍼"""
import logging
from pathlib import Path

from skills.wiki_skill import WIKI_SKILL_CLASSES, WIKI_SKILL_NAMES


def load_wiki_skills(wiki_path: str, registry) -> bool:
    """
    주어진 wiki_path로 위키 스킬들을 skill_registry에 등록합니다.
    기존 위키 스킬이 있으면 먼저 제거합니다.
    성공하면 True 반환.
    """
    path = Path(wiki_path)
    if not path.exists():
        logging.warning(f"[Wiki] 경로가 존재하지 않습니다: {wiki_path}")
        return False

    unload_wiki_skills(registry)

    for cls in WIKI_SKILL_CLASSES:
        instance = cls(wiki_path)
        registry.register(instance)
        logging.info(f"[Wiki] Loaded: {instance.name}")

    logging.info(f"[Wiki] {len(WIKI_SKILL_CLASSES)}개 스킬 로드 완료 ({wiki_path})")
    return True


def unload_wiki_skills(registry) -> None:
    """위키 스킬을 skill_registry에서 제거합니다."""
    for name in WIKI_SKILL_NAMES:
        registry.unregister(name)
        logging.info(f"[Wiki] Unloaded: {name}")
