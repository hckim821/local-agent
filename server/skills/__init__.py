import importlib
import inspect
import os
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
                for name, obj in inspect.getmembers(module, inspect.isclass):
                    if issubclass(obj, SkillBase) and obj is not SkillBase:
                        instance = obj()
                        self._skills[instance.name] = instance
                        print(f"[Skills] Loaded: {instance.name}")
            except Exception as e:
                print(f"[Skills] Failed to load {py_file.name}: {e}")

    def register(self, skill: SkillBase):
        self._skills[skill.name] = skill

    def get(self, name: str) -> SkillBase | None:
        return self._skills.get(name)

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
