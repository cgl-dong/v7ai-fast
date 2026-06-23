"""Skill auto-discovery.

Two discovery mechanisms:

1. Python modules (*.py) — scanned for @register_skill classes (transform skills).
   Drop a .py file here with a BaseSkill subclass + @register_skill decorator.

2. SKILL.md directories — each subdirectory containing a SKILL.md file is
   registered as a "tool" skill (e.g., ppt-generation, pdf-to-docx).

Both are triggered on `import app.services.skills` or by calling
`discover_all()` from skill_base.
"""
import importlib
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Track if discovery has already run
_discovered = False


def _discover_py_modules():
    """Import all .py modules in this package to trigger @register_skill."""
    global _discovered
    if _discovered:
        return
    _discovered = True

    skills_dir = Path(__file__).parent

    # Import all .py files (except __init__)
    for f in sorted(skills_dir.glob("*.py")):
        if f.name.startswith("_") or f.name.startswith("."):
            continue
        module_name = f.stem
        try:
            importlib.import_module(f"app.services.skills.{module_name}")
            logger.debug(f"Imported skill module: {module_name}")
        except Exception as e:
            logger.warning(f"Failed to import skill module '{module_name}': {e}")


def _discover_tool_skills():
    """Scan subdirectories for SKILL.md and register tool skills."""
    from app.services.skill_base import discover_tool_skills, registry

    skills_dir = str(Path(__file__).parent)
    tools = discover_tool_skills(skills_dir)
    existing_names = {s.name for s in registry.list_skills()}
    count = 0
    for tool in tools:
        if tool.name not in existing_names:
            registry.add_tool(tool)
            count += 1
    if count:
        logger.info(f"Discovered {count} tool skill(s) from SKILL.md")
    return count
