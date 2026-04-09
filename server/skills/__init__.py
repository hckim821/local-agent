import importlib
import inspect
import logging
import traceback
from pathlib import Path
from .skill_base import SkillBase


class SkillRegistry:
    def __init__(self):
        self._skills: dict[str, SkillBase] = {}

    def load_skills(self):
        skills_dir = Path(__file__).parent
        for py_file in skills_dir.glob("*.py"):
            if py_file.name.startswith("_") or py_file.name == "skill_base.py":
                continue
            module_name = f"skills.{py_file.stem}"
            try:
                module = importlib.import_module(module_name)
                for attr_name, obj in inspect.getmembers(module, inspect.isclass):
                    if obj is SkillBase:
                        continue
                    if not issubclass(obj, SkillBase):
                        continue
                    # Skip classes not defined in this module (imported ones)
                    if obj.__module__ != module.__name__:
                        continue
                    instance = obj()
                    self._skills[instance.name] = instance
                    logging.info(f"[Skills] Loaded: {instance.name} ({py_file.name})")
            except Exception:
                logging.error(
                    f"[Skills] Failed to load {py_file.name}:\n{traceback.format_exc()}"
                )

    def register(self, skill: SkillBase):
        self._skills[skill.name] = skill

    def get(self, name: str) -> SkillBase | None:
        skill = self._skills.get(name)
        if skill is None:
            logging.warning(
                f"[Skills] '{name}' not found. Registered: {list(self._skills.keys())}"
            )
        return skill

    def list_all(self) -> list[dict]:
        return [
            {
                "name": s.name,
                "description": s.description,
                "parameters": s.parameters,
            }
            for s in self._skills.values()
        ]

    def to_tools(self) -> list[dict]:
        return [s.to_tool_definition() for s in self._skills.values()]


skill_registry = SkillRegistry()
