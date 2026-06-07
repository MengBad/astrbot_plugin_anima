# Test Report - v1.2.4 Release Candidate

## Environment

- OS: Windows
- Shell: PowerShell
- Python launcher: `py -3`
- Pytest config: `pytest.ini`

## Commands

```powershell
py -3 -m py_compile anima\sylanne_alpha\personality_drift_viewer.py anima\sylanne_alpha\scar_explorer.py anima\sylanne_alpha\desire_dashboard.py anima\sylanne_alpha\memory_explorer.py anima\sylanne_alpha\state_inspector.py anima\sylanne_alpha\state_persistence.py anima\sylanne_alpha\llm_request_pipeline.py anima\sylanne_alpha\webui_routes.py anima\sylanne_alpha\webui_server.py main.py plugin_api.py
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
- prompt debug snapshot redaction
- prompt injection assembled runtime event emission
- Cognitive Timeline Portal panel contract
- shared WebUI and independent WebUI `/api/runtime_events` route registration
- shared WebUI and independent WebUI `/api/prompt_debug` route registration
- State Inspector redaction and non-destructive dirty flag diagnostics
- shared WebUI and independent WebUI `/api/state_inspector` route registration
- Portal State Inspector card/API hook contract
- Portal JavaScript syntax check for the Observatory shell
- Memory Explorer redaction for memory text, graph labels, and edge relations
- shared WebUI and independent WebUI `/api/memory_explorer` route registration
- Portal Memory Explorer card/API hook contract
- Desire Dashboard redaction for desire content, target UMO, and target user identifiers
- shared WebUI and independent WebUI `/api/desire_dashboard` route registration
- Portal Desire Dashboard card/API hook contract
- Scar Explorer redaction for scar source text and legacy raw fields
- shared WebUI and independent WebUI `/api/scar_explorer` route registration
- Portal Scar Explorer card/API hook contract
- Personality Drift Viewer redaction for persona_core text and mutation descriptions
- shared WebUI and independent WebUI `/api/personality_drift` route registration
- Portal Personality Drift card/API hook contract

## Latest Result

- `py -3 -m py_compile ...`: passed
- `node -e "... vm.Script(...portal script ...)"`: passed
- `py -3 -m pytest tests\test_desire_dashboard.py tests\test_cognitive_timeline_webui.py -q`: `7 passed`
- `py -3 -m pytest tests\test_scar_explorer.py tests\test_cognitive_timeline_webui.py -q`: `8 passed`
- `py -3 -m pytest tests\test_personality_drift_viewer.py tests\test_cognitive_timeline_webui.py -q`: `9 passed`
- `py -3 -m pytest tests\test_memory_explorer.py tests\test_cognitive_timeline_webui.py -q`: `6 passed`
- `py -3 -m pytest tests\test_state_inspector.py tests\test_cognitive_timeline_webui.py -q`: `5 passed`
- `py -3 -m pytest tests\test_cognitive_timeline_webui.py tests\test_runtime_observability.py -q`: `7 passed`
- `py -3 -m pytest tests\test_runtime_observability.py tests\test_phase2_stability_fixes.py -q`: `9 passed`
- `py -3 -m pytest -q`: `371 passed, 50 warnings`

## Warnings

The remaining warnings are existing `DeprecationWarning: __package__ != __spec__.parent` warnings emitted while importing `main.py` in the test environment. They do not fail the suite and were not introduced by the Runtime Event Bus behavior.
