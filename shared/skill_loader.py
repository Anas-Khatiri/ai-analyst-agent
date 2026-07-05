from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from shared.schemas.finding import Finding
from shared.skill_registry import SkillMetadata


def load_skill_script(script_path: Path) -> ModuleType:
    """Dynamically loads a skill's Python script as a module by file path.

    Skill scripts are intentionally not an installable package
    (.agents/CONTEXT.md §6.4) — they must stay runnable standalone. This
    adds the script's own directory to sys.path before executing it, so a
    script's sibling imports (e.g. `import _data_drift_analysis_core as
    core`) resolve without any ad hoc sys.path manipulation inside the
    script itself.
    """
    if not script_path.is_file():
        raise FileNotFoundError(f"Skill script not found: {script_path}")

    script_dir = str(script_path.parent)
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)

    module_name = script_path.stem
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot build module spec for {script_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


async def execute_skill(
    meta: SkillMetadata, script_path: Path, params: dict[str, object]
) -> Finding:
    """Loads and executes a skill's `run()` entrypoint, per
    DYNAMIC_DISCOVERY_DESIGN.md §3.3.

    Exceptions propagate uncaught — this function never decides what a
    failure means. The caller (the Skill Executor stage in
    agents/ml_analyst_agent.py) is responsible for catching a failure and
    marking that skill "unavailable" per ml_analyst_agent.md §11, rather
    than this loader silently swallowing or reinterpreting it.
    """
    module = load_skill_script(script_path)
    run_func = getattr(module, "run", None)
    if run_func is None:
        raise AttributeError(f"Skill '{meta.name}' script lacks a run() entrypoint.")

    result = await run_func(**params)
    if not isinstance(result, Finding):
        raise TypeError(
            f"Skill '{meta.name}' run() must return a Finding, got {type(result).__name__}."
        )
    return result
