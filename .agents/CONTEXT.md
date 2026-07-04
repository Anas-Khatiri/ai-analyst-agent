# Local Project Context & Secure Coding Standards

This document establishes the "paved roads" and standards for the `ml-analyst-agent` repository. All agents and developers must strictly adhere to these guidelines.

---

## 1. Core Coding Standards
*   **Strict Type Hinting**: Every function, method, and class must use Python type hints for all parameters and return types.
*   **Clean Code (SOLID)**: Favor composition over inheritance. Keep modules narrow and specialized.
*   **Static Analysis**: Code must pass Ruff linting and formatting check, and Mypy typing validation before committing.

---

## 2. Secure Coding Guidelines (Paved Roads)

### 2.1 Tool Input Validation
*   Every agent tool must validate its incoming arguments against a strict Pydantic schema rather than parsing raw dictionaries or unstructured strings.
*   Tool schemas must forbid extra arguments (set `extra = "forbid"` or `model_config = {"extra": "forbid"}`).

### 2.2 No Raw Shell Execution
*   Never use raw shell execution tools (like `run_command` or Python `subprocess`) in agent actions.
*   All operations must use parameterized Python SDK functions or strictly typed wrappers (e.g., `restart_dag(dag_id: str)` instead of `sh "airflow dags trigger <id>"`).

### 2.3 PII and Secret Isolation
*   Sensitive employee or user data (SSNs, credit cards, emails) must be deterministic-masked using the PII Scrubbing Utility before logs or strings reach the LLM.
*   API keys, passwords, and tokens must never be logged or embedded in traces.

### 2.4 Pre-Commit Remediation Loop
*   If a Git commit fails due to a pre-commit hook violation (e.g., Ruff check error, Semgrep finding), you must treat the violation as a refactoring task, apply targeted fixes, run tests to verify no regressions, and attempt to commit again.

### 2.5 MCP Adoption Is Deferred to Phase 6/7, Not Phase 3-5
*   MCP will serve as the eventual mechanism for decoupling agents from real infrastructure (Airflow, Postgres, Git). Do **not** stand up an MCP server against simulated data.
*   Until Phase 6/7 wire in real infrastructure, keep the existing seam: agents call narrow, Pydantic-schema'd functions in `shared/tools/*.py`, which call `services/mock_env/*.py`. Swapping the mock adapter for a direct SDK call or an `MCPToolset` client later should not require changing any agent, schema, or the orchestration graph.

---

## 3. Telemetry & Logging Standards
*   **Structured Output**: Use JSON-structured logs with standard metadata (`timestamp`, `level`, `module`, `session_id`).
*   **Contextual Logging**: Log exceptions with exact stack traces but ensure variable parameters do not contain sensitive data.

---

## 4. Testing & Evaluation Rules
*   **Unit & Integration Tests**: Test functions, utilities, and endpoints with `pytest`. Assert on types, schemas, status codes, and deterministic outputs.
*   **No Flaky Pytest Assertions**: Never write pytest assertions that validate LLM text response contents (e.g., checking for specific words).
*   **EDD (Evaluation-Driven Development)**: Qualitative agent behaviors must be tested using an evaluation harness with LLM-as-judge scorecards scoring 1-5.

---

## 5. TDD Planning Gate
During the planning phase of any new feature or agent tool, you must decompose the task and document it. Every implementation plan MUST include a dedicated **Security Boundaries & Assertions** section outlining specific edge cases that could exploit the feature, including:
1.  How tool parameters are validated.
2.  How prompt injection vectors are neutralized.
3.  How PII leakage is prevented.
4.  Verification commands for validating the security boundaries.

---

## 6. Skill & Agent Tool Architecture Patterns

### 6.1 Shared-Core-Plus-Focused-Reports
The moment a skill produces more than one related report or deliverable, factor the shared computation into a private `_<domain>_core.py` module *before* writing the second report. A report script must never import from a sibling report script — only from the shared core.
*   The core module owns only Pydantic result models and pure computation functions: no CLI, no `argparse`, no demo/fixture data.
*   Core functions take plain scalar/primitive parameters (`bool`, `float`, `str`, ...), never a config object owned by one specific consumer.

### 6.2 One Tool, One Question
A `FunctionTool` answers exactly one well-defined question. Do not bundle unrelated computations — e.g., drift detection, dataset-level performance, per-segment performance, and a retraining recommendation — into a single tool call. Split by question: "did it drift," "did it regress," "where did it regress," and "what should we do about it" are separate tools, not one.

### 6.3 Deterministic Combination, Never LLM Judgment
When a decision must combine the outputs of multiple tools — e.g., a retraining recommendation combining drift, aggregate performance, and segment findings — that combination is itself a deterministic Python function exposed as its own tool, never left to the model to derive by reasoning over raw numbers in context.

### 6.4 Dynamic Skill-Script Loading and Sibling Imports
Agent tools dynamically load Phase 2 skill scripts via `shared/skill_loader.py::load_skill_script`, which executes a script by file path (skill scripts are intentionally not an installable package — they must stay runnable standalone). If a skill script needs a sibling module, rely on the loader — it adds the script's own directory to `sys.path` before executing it. Do not add ad hoc `sys.path` manipulation inside individual skill scripts.
