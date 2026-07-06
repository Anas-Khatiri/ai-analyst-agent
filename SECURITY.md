# SECURITY.md

## Overview
This repository implements a production‑grade **security hardening layer** for the ML Analyst Agent.  The security package lives under `shared/security/` and provides:
- **Input validation** using Pydantic models.
- **PII redaction** before any logging or external transmission.
- **Tool allow‑list enforcement** – only skills marked as `investigative` may be executed.
- **Semgrep CI integration** to catch dangerous patterns.

## Core Modules
| Module | Purpose |
|---|---|
| `validation.py` | Pydantic based schemas (`SecureModel`) that validate external inputs.
| `redaction.py` | Regex‑based redaction of emails, IPs, tokens, etc.
| `exceptions.py` | Central `SecurityError` hierarchy.
| `skill_loader.py` (updated) | Enforces the **allow‑list** by checking `SkillMetadata.role` before loading a skill.

## Extending Safely
When adding new security‑related functionality or new skills, follow these steps:
1. **Define a clear contract** – create a Pydantic model in `validation.py` if you need to validate new data structures.
2. **Add allow‑list metadata** – in each skill’s `SKILL.md` front‑matter, ensure the `role` field is set to `investigative` (or another allowed role) and that the skill is registered in `shared/skill_registry.py`.
3. **Update the allow‑list check** – if you introduce a new role that should also be allowed, modify the guard in `shared/skill_loader.py`:
   ```python
   if meta.role not in {"investigative", "my_new_role"}:
       raise SecurityError(...)
   ```
4. **Redact any new secret patterns** – extend `PII_REGEXES` in `redaction.py` with appropriate patterns and add unit tests.
5. **Write tests** – add coverage in `tests/security/` for the new logic (validation, redaction).
6. **Semgrep rule** – if the new code introduces a risky operation (e.g., `os.system`), add a rule to `.semgrep.yml` so CI will fail on regressions.

## CI / CD
- The repository includes a GitHub Actions workflow at `.github/workflows/semgrep.yml` that runs on each push and fails on **high** or **critical** findings.
- Ensure new modules are imported in `__init__.py` so they are linted.

## Common Pitfalls
- **Do not** bypass the allow‑list by calling `load_skill_script` directly – always go through `execute_skill`.
- **Never** use `subprocess.run(..., shell=True)` or `os.system`; replace with safe Python APIs or add a Semgrep rule if unavoidable.
- Remember to **redact** any newly introduced secret‑type fields before logging.

## Further Reading
- `docs/specifications/SYSTEM_SPEC.md` – overall system architecture.
- `shared/security/redaction.py` – regular expressions used for PII removal.
- `shared/security/validation.py` – how to declare secure Pydantic models.

---
*This document is intended for developers contributing new capabilities or maintaining the security posture of the ML Analyst Agent.*
