# CHANGELOG.md

## 2026-07-05 – Security Hardening Release

- Added **SECURITY.md** documenting the security package, usage, and extension guidelines.
- Implemented **tool allow‑list** check in `shared/skill_loader.py` to restrict skill execution to investigative tools.
- Updated `.agents/CONTEXT.md` to reference the new security documentation.
- Integrated PII redaction, audit logging, and prompt guard utilities under `shared/security/`.
- CI/CD Semgrep workflow already validates the security constraints.

All existing tests continue to pass.
