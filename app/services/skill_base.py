"""Skill system — pluggable document transformation & tool pipeline.

Two skill types are supported:

  transform — Document conversion (e.g. PDF→DOCX). Subclass BaseSkill,
              decorate with @register_skill, run in-process during indexing.

  tool      — CLI / script-based tools (e.g. ppt-generation). Discovered
              from SKILL.md files in subdirectories under skills/.

All skills are auto-discovered on import of app.services.skills and synced
to the skill_definitions database table at startup.
"""
import logging
import os
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Tuple, Optional, Dict

logger = logging.getLogger(__name__)


# ── Skill Info (lightweight descriptor for both types) ─────────────


class SkillInfo:
    """Lightweight skill metadata used for listing and discovery."""

    def __init__(
        self,
        name: str,
        skill_type: str,          # "transform" | "tool"
        description: str = "",
        input_types: List[str] = None,
        output_type: str = "",
        metadata: Dict = None,
    ):
        self.name = name
        self.skill_type = skill_type
        self.description = description
        self.input_types = input_types or []
        self.output_type = output_type
        self.metadata = metadata or {}

    def can_handle(self, file_type: str) -> bool:
        return file_type.lower() in {t.lower() for t in self.input_types}

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "skill_type": self.skill_type,
            "description": self.description,
            "input_types": self.input_types,
            "output_type": self.output_type,
            "metadata": self.metadata,
        }

    def __repr__(self) -> str:
        return f"<SkillInfo {self.name} [{self.skill_type}]: {self.input_types} → {self.output_type}>"


# ── Transform Skill (BaseSkill) ────────────────────────────────────


class BaseSkill(ABC):
    """Abstract base for a document TRANSFORM skill.

    Subclasses must define: name, description, input_types, output_type, process().
    """

    name: str = ""
    description: str = ""
    input_types: List[str] = []
    output_type: str = ""

    def can_handle(self, file_type: str) -> bool:
        return file_type.lower() in {t.lower() for t in self.input_types}

    @abstractmethod
    def process(self, content: bytes, filename: str) -> Tuple[bytes, str, str]:
        ...

    def to_info(self) -> SkillInfo:
        return SkillInfo(
            name=self.name,
            skill_type="transform",
            description=self.description,
            input_types=self.input_types,
            output_type=self.output_type,
        )

    def __repr__(self) -> str:
        return f"<Skill {self.name}: {self.input_types} → {self.output_type}>"


# ── Registry ───────────────────────────────────────────────────────


class SkillRegistry:
    """Singleton registry for all skills (transform + tool).

    Transform skills are registered via @register_skill decorator.
    Tool skills are discovered from SKILL.md files and added via add_tool().
    """

    def __init__(self):
        self._transforms: dict[str, BaseSkill] = {}   # name → BaseSkill instance
        self._tools: dict[str, SkillInfo] = {}         # name → SkillInfo

    # -- Registration --

    def register(self, skill: BaseSkill) -> None:
        """Register a transform skill instance."""
        if skill.name in self._transforms:
            logger.warning(f"Transform skill '{skill.name}' already registered, overwriting")
        self._transforms[skill.name] = skill
        logger.info(f"Transform skill registered: {skill.name} ({skill.input_types} → {skill.output_type})")

    def unregister(self, name: str) -> bool:
        if name in self._transforms:
            del self._transforms[name]
            return True
        if name in self._tools:
            del self._tools[name]
            return True
        return False

    def add_tool(self, info: SkillInfo) -> None:
        """Register a tool skill discovered from SKILL.md."""
        if info.name in self._tools:
            logger.warning(f"Tool skill '{info.name}' already registered, overwriting")
        self._tools[info.name] = info
        logger.info(f"Tool skill registered: {info.name} [{info.skill_type}]")

    # -- Lookup --

    def get(self, name: str) -> Optional[BaseSkill]:
        """Get a transform skill by name (returns BaseSkill or None)."""
        return self._transforms.get(name)

    def get_info(self, name: str) -> Optional[SkillInfo]:
        """Get any skill's info by name."""
        if name in self._transforms:
            return self._transforms[name].to_info()
        return self._tools.get(name)

    def list_skills(self) -> List[SkillInfo]:
        """Return all skills (both types) as SkillInfo list."""
        result = [s.to_info() for s in self._transforms.values()]
        result.extend(self._tools.values())
        return result

    def list_transform_skills(self) -> List[BaseSkill]:
        """Return only transform skills (BaseSkill instances)."""
        return list(self._transforms.values())

    # -- Pipeline (transform only) --

    def find_for_input(self, file_type: str) -> List[BaseSkill]:
        return [s for s in self._transforms.values() if s.can_handle(file_type)]

    def build_pipeline(self, input_type: str, skill_names: List[str]) -> List[BaseSkill]:
        pipeline: List[BaseSkill] = []
        current_type = input_type
        for name in skill_names:
            skill = self.get(name)
            if skill is None:
                available = list(self._transforms.keys())
                raise ValueError(f"Transform skill '{name}' not found. Available: {available}")
            if not skill.can_handle(current_type):
                raise ValueError(
                    f"Skill '{name}' expects input types {skill.input_types}, "
                    f"but current type is '{current_type}'"
                )
            pipeline.append(skill)
            current_type = skill.output_type
        return pipeline

    def run_pipeline(
        self, content: bytes, filename: str, file_type: str, skill_names: List[str],
    ) -> Tuple[bytes, str, str]:
        """Run a transform skill pipeline on file content."""
        if not skill_names:
            return content, filename, file_type

        pipeline = self.build_pipeline(file_type, skill_names)
        current_content, current_filename, current_type = content, filename, file_type

        for skill in pipeline:
            logger.info(
                f"Running skill '{skill.name}': {current_type} → {skill.output_type} "
                f"({current_filename}, {len(current_content)} bytes)"
            )
            try:
                current_content, current_filename, current_type = skill.process(
                    current_content, current_filename
                )
                logger.info(
                    f"Skill '{skill.name}' complete: new_type={current_type}, "
                    f"new_name={current_filename}, {len(current_content)} bytes"
                )
            except Exception as e:
                logger.error(f"Skill '{skill.name}' failed on {current_filename}: {e}")
                raise RuntimeError(f"Skill '{skill.name}' failed: {e}") from e

        return current_content, current_filename, current_type


# ── Global singleton ───────────────────────────────────────────────

registry = SkillRegistry()


def register_skill(cls):
    """Decorator to auto-register a transform skill class."""
    instance = cls()
    registry.register(instance)
    return cls


# ── SKILL.md Discovery ─────────────────────────────────────────────


_YAML_FRONTMATTER_RE = re.compile(r'^---\s*\n(.*?)\n---', re.DOTALL)


def _parse_skill_md(path: Path) -> Optional[SkillInfo]:
    """Parse a SKILL.md file and extract skill metadata from YAML frontmatter."""
    try:
        content = path.read_text(encoding="utf-8")
    except Exception:
        return None

    m = _YAML_FRONTMATTER_RE.match(content)
    if not m:
        return None

    frontmatter = m.group(1)

    # Simple YAML parser for name/description/category
    name = None
    description = ""
    category = ""

    for line in frontmatter.split("\n"):
        line = line.rstrip()
        if line.startswith("name:"):
            name = line.split(":", 1)[1].strip().strip('"').strip("'")
        elif line.startswith("description:"):
            description = line.split(":", 1)[1].strip().strip('"').strip("'")
        elif line.startswith("category:"):
            category = line.split(":", 1)[1].strip().strip('"').strip("'")

    if not name:
        return None

    return SkillInfo(
        name=name,
        skill_type="tool",
        description=description,
        input_types=[],
        output_type="",
        metadata={
            "source_dir": str(path.parent),
            "has_script": (path.parent / "scripts").is_dir(),
            "category": category,
        },
    )


def discover_tool_skills(skills_dir: str) -> List[SkillInfo]:
    """Scan skills_dir subdirectories for SKILL.md files and parse them.

    Each subdirectory that contains a SKILL.md file is registered as a
    "tool" skill. Directories named with hyphens (e.g. ppt-generation)
    are matched to their SKILL.md for metadata.
    """
    discovered: List[SkillInfo] = []
    root = Path(skills_dir)

    if not root.is_dir():
        return discovered

    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name.startswith("_") or entry.name == "__pycache__":
            continue

        # Look for SKILL.md in the directory
        skill_md = entry / "SKILL.md"
        if not skill_md.exists():
            # Also check one level deeper (e.g. pdf-to-docx/pdf-to-docx/SKILL.md)
            for sub in entry.iterdir():
                if sub.is_dir() and (sub / "SKILL.md").exists():
                    skill_md = sub / "SKILL.md"
                    break

        if skill_md.exists():
            info = _parse_skill_md(skill_md)
            if info:
                discovered.append(info)

    return discovered


def discover_all(skills_package_path: str = None) -> int:
    """Run full discovery: import Python skills + scan SKILL.md dirs.

    Returns total number of skills discovered.
    """
    count = 0

    # 1. Import Python modules (triggers @register_skill)
    try:
        import app.services.skills as _skills_pkg
        # Trigger dynamic import of all .py files
        _skills_pkg._discover_py_modules()
    except Exception as e:
        logger.warning(f"Python skill discovery failed: {e}")

    count += len(registry.list_transform_skills())

    # 2. Discover tool skills from SKILL.md
    if skills_package_path is None:
        skills_package_path = str(Path(__file__).parent / "skills")

    tools = discover_tool_skills(skills_package_path)
    for tool in tools:
        if tool.name not in {s.name for s in registry.list_skills()}:
            registry.add_tool(tool)
            count += 1

    logger.info(f"Skill discovery complete: {count} total ({len(registry.list_transform_skills())} transform, {len(registry._tools)} tool)")
    return count


def sync_skill_definitions(db_session) -> int:
    """Sync discovered skills to the skill_definitions database table.

    - Inserts new skills not yet in DB
    - Updates name/description/type for existing skills
    - Does NOT delete skills removed from code (preserves history)

    Returns number of skills synced.
    """
    import json
    from app.core.database import SkillDefinition

    skills = registry.list_skills()
    synced = 0

    for info in skills:
        existing = db_session.query(SkillDefinition).filter(
            SkillDefinition.name == info.name
        ).first()

        if existing:
            # Update if changed
            changed = False
            if existing.skill_type != info.skill_type:
                existing.skill_type = info.skill_type
                changed = True
            if existing.description != info.description:
                existing.description = info.description
                changed = True
            new_input = json.dumps(info.input_types, ensure_ascii=False) if info.input_types else None
            if existing.input_types != new_input:
                existing.input_types = new_input
                changed = True
            if existing.output_type != info.output_type:
                existing.output_type = info.output_type
                changed = True
            new_meta = json.dumps(info.metadata, ensure_ascii=False) if info.metadata else None
            if existing.metadata_json != new_meta:
                existing.metadata_json = new_meta
                changed = True
            if changed:
                synced += 1
        else:
            # Insert new
            db_session.add(SkillDefinition(
                name=info.name,
                skill_type=info.skill_type,
                description=info.description,
                input_types=json.dumps(info.input_types, ensure_ascii=False) if info.input_types else None,
                output_type=info.output_type or None,
                metadata_json=json.dumps(info.metadata, ensure_ascii=False) if info.metadata else None,
                is_active=True,
            ))
            synced += 1

    if synced:
        db_session.commit()
        logger.info(f"Skill definitions synced: {synced} updated/inserted")
    return synced
