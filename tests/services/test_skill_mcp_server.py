from __future__ import annotations

from services.mcp.skill_mcp_server import build_server, invoke_investigative_skill
from shared.skill_registry import SkillRegistry


def _registry() -> SkillRegistry:
    registry = SkillRegistry()
    registry.scan_skills()
    return registry


async def test_build_server_excludes_terminal_skills() -> None:
    server = build_server(registry=_registry(), skill_parameters={})

    tools = await server.list_tools()
    names = {tool.name for tool in tools}

    assert names == {"data_drift_analysis", "model_performance_analysis"}
    assert "root_cause_prioritization" not in names
    assert "incident_summary" not in names


async def test_build_server_tool_metadata_matches_skill_metadata() -> None:
    registry = _registry()
    server = build_server(registry=registry, skill_parameters={})

    tools = await server.list_tools()
    for tool in tools:
        meta = registry.get(tool.name)
        assert meta is not None
        assert tool.description == meta.description


async def test_build_server_tools_are_zero_argument() -> None:
    """Structural guard: every investigative tool's MCP input schema must
    have no properties, so the LLM can never be asked to fabricate a
    dataset identifier or other skill parameter (ADR-005 §1)."""
    server = build_server(registry=_registry(), skill_parameters={})

    tools = await server.list_tools()
    assert tools
    for tool in tools:
        assert tool.inputSchema.get("properties", {}) == {}
        assert not tool.inputSchema.get("required")


async def test_invoke_investigative_skill_executes_skill_and_returns_finding_dict() -> None:
    registry = _registry()
    meta = registry.get("data_drift_analysis")
    assert meta is not None
    script_path = registry.resolve_script_path(meta)
    params = {
        "reference_dataset_id": "fraud_detection_xgboost",
        "current_dataset_id": "fraud_detection_xgboost",
        "numerical_features": ["transaction_amount"],
        "categorical_features": ["user_zipcode", "device_type"],
        "min_sample_size": 100,
    }

    result = await invoke_investigative_skill(meta, script_path, params)

    assert "confidence_score" in result
    confidence_score = result["confidence_score"]
    assert isinstance(confidence_score, float)
    assert confidence_score >= 0.8


async def test_invoke_investigative_skill_returns_error_dict_on_bad_params() -> None:
    registry = _registry()
    meta = registry.get("model_performance_analysis")
    assert meta is not None
    script_path = registry.resolve_script_path(meta)

    result = await invoke_investigative_skill(meta, script_path, {})

    assert "error" in result
