# Test Report - v1.3.0

## Environment

- OS: Windows
- Shell: PowerShell
- Python launcher: `py -3`
- Pytest config: `pytest.ini`

## Commands

```powershell
py -3 -m pytest --co -q
```

```powershell
py -3 -m pytest -q
```

## Coverage Summary

| Category | Tests |
|----------|-------|
| Core Stability (Phase 2) | 6 |
| WebUI Routes | 21 |
| Cognitive Observatory | 14 |
| Safety Redaction | 12 |
| High-Risk Rollback | 4 |
| Capability System | 45 |
| Session Isolation | 17 |
| Persona Injection | 11 |
| Desire System | 12 |
| Filters & Similarity | 40 |
| Other | 217 |
| **Total** | **409** |

## Latest Result

- `py -3 -m pytest --co -q`: `409 items collected`
- `py -3 -m pytest -q`: `409 passed, 50 warnings in 32.99s`

## Warnings

The remaining warnings are existing `DeprecationWarning: __package__ != __spec__.parent` warnings emitted while importing `main.py` in the test environment. They do not fail the suite and were not introduced by the v1.3.0 changes.

## Coverage Added This Round

- Version number unification verification
- Documentation consistency checks
- All existing test suites remain green

## Conclusion

All 409 tests pass. The test suite is healthy and covers core stability, WebUI routes, observability panels, safety redaction, capability system, session isolation, and persona injection. No regressions detected.
