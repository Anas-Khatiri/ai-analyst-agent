from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

SkillRole = Literal["investigative", "terminal_ranking", "terminal_reporting"]

DEFAULT_SKILLS_DIR = Path(__file__).resolve().parents[1] / "skills"


class SkillMetadata(BaseModel):
    """Per DYNAMIC_DISCOVERY_DESIGN.md §3.2 and skill_contract.md §3, extended
    with `role`/`terminal_order` so the agent can identify the terminal wave
    generically instead of hardcoding skill names."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    required_inputs: dict[str, str] = Field(default_factory=dict)
    script_path: str
    version: str
    scope_boundary: str
    role: SkillRole = "investigative"
    terminal_order: int | None = None
    alert_triggers: list[str] = Field(default_factory=list)


class SkillRegistry:
    """Scans `skills/` and parses each SKILL.md's YAML frontmatter into a
    SkillMetadata map, per ADR-001-dynamic-skills.md and
    DYNAMIC_DISCOVERY_DESIGN.md §3.2. Adding a new skill requires no change
    here — it just needs a conformant SKILL.md."""

    def __init__(self, skills_dir: Path = DEFAULT_SKILLS_DIR) -> None:
        self.skills_dir = skills_dir
        self.registry: dict[str, SkillMetadata] = {}

    def scan_skills(self) -> None:
        self.registry = {}
        if not self.skills_dir.is_dir():
            return
        for skill_dir in sorted(self.skills_dir.iterdir()):
            if not skill_dir.is_dir():
                continue
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.is_file():
                continue
            metadata = self._parse_skill_md(skill_md)
            if metadata is not None:
                self.registry[metadata.name] = metadata

    def _parse_skill_md(self, file_path: Path) -> SkillMetadata | None:
        content = file_path.read_text(encoding="utf-8")
        if not content.startswith("---"):
            return None
        parts = content.split("---", 2)
        if len(parts) < 3:
            return None
        data = yaml.safe_load(parts[1])
        if not isinstance(data, dict):
            return None
        return SkillMetadata(**data)

    def resolve_skills_for_alert(self, alert_type: str) -> list[SkillMetadata]:
        """Signal-based routing per skill_selection_engine.md §3.1."""
        return [meta for meta in self.registry.values() if alert_type in meta.alert_triggers]

    def terminal_skills(self) -> list[SkillMetadata]:
        """Every non-investigative skill, ordered by terminal_order, per
        skill_selection_engine.md §5.3."""
        terminal = [meta for meta in self.registry.values() if meta.role != "investigative"]
        return sorted(terminal, key=lambda meta: meta.terminal_order or 0)

    def get(self, name: str) -> SkillMetadata | None:
        return self.registry.get(name)

    def resolve_script_path(self, meta: SkillMetadata) -> Path:
        return self.skills_dir / meta.name / meta.script_path

    def is_empty(self) -> bool:
        return not self.registry
