"""MCP server exposing investigative skills as MCP tools, per
ADR-005-mcp-skill-invocation.md and ADR-007-skill-selection-gate.md.

This is the server-side mirror of what agents/reasoning/react_agent.py's
make_investigative_tool_function/build_investigative_tools used to do
in-process: one zero-argument tool per investigative skill (terminal skills
are never exposed here, matching ADR-004 §3.1 / .agents/CONTEXT.md §6.8).

A fresh instance of this server is spawned as a stdio subprocess per
incident investigation (see agents/reasoning/react_agent.py). The incident's resolved
`skill_parameters` are passed in via the SKILL_PARAMETERS_JSON environment
variable, read once at startup — this keeps every tool's MCP input schema
argument-free, so the LLM's only decision is *whether* to call a tool, never
fabricating dataset identifiers it has no way to know (the same invariant
the in-process closures enforced by construction).

Per ADR-007-skill-selection-gate.md, `agents/planning/skill_selector.py` decides
*which* investigative skills are even worth exposing before this server is
spawned. That decision is passed in via the SELECTED_SKILLS_JSON
environment variable, also read once at startup: a concrete set restricts
tool registration to those names, `None` (unset) restores the pre-ADR-007
behavior of exposing every investigative skill (used by callers/tests that
don't run the selection stage).
"""

from __future__ import annotations

import json
import os
from collections.abc import Awaitable, Callable
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from infra.skill_loader import execute_skill
from infra.skill_registry import SkillMetadata, SkillRegistry


async def invoke_investigative_skill(
    meta: SkillMetadata, script_path: Path, resolved_params: dict[str, object]
) -> dict[str, object]:
    """Executes one investigative skill and returns its Finding as a plain
    dict, or `{"error": ...}` on failure. Never raises — a skill failure
    must surface as a normal tool result, not an MCP-protocol-level error
    or an exception that kills the caller's ReAct loop."""
    try:
        finding = await execute_skill(meta, script_path, resolved_params)
    except Exception as exc:
        return {"error": str(exc)}
    return finding.model_dump(mode="json")


def _load_skill_parameters() -> dict[str, dict[str, object]]:
    raw = os.environ.get("SKILL_PARAMETERS_JSON")
    if not raw:
        return {}
    parsed: dict[str, dict[str, object]] = json.loads(raw)
    return parsed


def _load_selected_skill_names() -> set[str] | None:
    """`None` means "no selection stage ran" -> expose every investigative
    skill (pre-ADR-007 behavior). A JSON list (including empty) means the
    selection stage ran and its answer, however narrow, must be honored."""
    raw = os.environ.get("SELECTED_SKILLS_JSON")
    if not raw:
        return None
    names: list[str] = json.loads(raw)
    return set(names)


def build_server(
    registry: SkillRegistry | None = None,
    skill_parameters: dict[str, dict[str, object]] | None = None,
    selected_skill_names: set[str] | None = None,
) -> FastMCP:
    """Builds (does not run) the MCP server. Registry/params/selection are
    injectable so tests never need to touch environment variables or a real
    skill scan unless they want to.

    `selected_skill_names=None` (the default) exposes every investigative
    skill, matching this server's behavior before ADR-007's pre-ReAct
    selection gate existed. A concrete set (including the empty set)
    restricts registration to those names only.
    """
    registry = registry or SkillRegistry()
    if not registry.registry:
        registry.scan_skills()
    resolved_skill_parameters = (
        skill_parameters if skill_parameters is not None else _load_skill_parameters()
    )
    resolved_selected_skill_names = (
        selected_skill_names if selected_skill_names is not None else _load_selected_skill_names()
    )

    mcp = FastMCP("pipeline-sentinel-skills")
    for meta in registry.investigative_skills():
        if (
            resolved_selected_skill_names is not None
            and meta.name not in resolved_selected_skill_names
        ):
            continue
        script_path = registry.resolve_script_path(meta)
        resolved_params = resolved_skill_parameters.get(meta.name, {})

        def _make_tool(
            meta: SkillMetadata = meta,
            script_path: Path = script_path,
            resolved_params: dict[str, object] = resolved_params,
        ) -> Callable[[], Awaitable[dict[str, object]]]:
            async def _tool() -> dict[str, object]:
                return await invoke_investigative_skill(meta, script_path, resolved_params)

            return _tool

        mcp.tool(name=meta.name, description=meta.description)(_make_tool())
    return mcp


mcp_server = build_server()

if __name__ == "__main__":
    mcp_server.run()
