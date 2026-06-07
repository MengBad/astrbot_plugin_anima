# Test Report - v1.2.4 Release Candidate

## Environment

- OS: Windows
- Shell: PowerShell
- Python launcher: `py -3`
- Pytest config: `pytest.ini`

## Commands

```powershell
py -3 -m py_compile main.py plugin_api.py anima\sylanne_alpha\observability.py anima\sylanne_alpha\webui_routes.py anima\sylanne_alpha\llm_response_pipeline.py anima\mixins\state_io.py anima\mixins\desire.py
```

```powershell
py -3 -m pytest tests\test_runtime_observability.py tests\test_phase2_stability_fixes.py -q
```

```powershell
py -3 -m pytest -q
```

## Coverage Added This Round

- corrupt state backup instead of destructive overwrite
- atomic state write
- atomic desire queue update
- invalid token budget config fallback/clamp
- response observation when realtime intercept is disabled
- cron response exclusion from observation
- Runtime Event Bus record/filter/stat behavior
- Runtime Event Bus payload truncation
- Runtime Event Bus JSONL timeline persistence and reload
- response observation runtime event emission
- Cognitive Timeline Portal panel contract
- shared WebUI and independent WebUI `/api/runtime_events` route registration

## Latest Result

- `py -3 -m py_compile ...`: passed
- `py -3 -m pytest tests\test_cognitive_timeline_webui.py tests\test_runtime_observability.py -q`: `5 passed`
- `py -3 -m pytest tests\test_runtime_observability.py tests\test_phase2_stability_fixes.py -q`: `9 passed`
- `py -3 -m pytest -q`: `359 passed, 50 warnings`

## Warnings

The remaining warnings are existing `DeprecationWarning: __package__ != __spec__.parent` warnings emitted while importing `main.py` in the test environment. They do not fail the suite and were not introduced by the Runtime Event Bus behavior.
