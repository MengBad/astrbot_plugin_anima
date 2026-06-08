# Test Report - v1.2.5 Release Candidate

## Environment

- OS: Windows
- Shell: PowerShell
- Python launcher: `py -3`
- Pytest config: `pytest.ini`

## Commands

```powershell
py -3 -m py_compile anima\sylanne_alpha\memory_recall_replay.py anima\sylanne_alpha\desire_evolution.py anima\sylanne_alpha\session_replay.py anima\sylanne_alpha\reasoning_trace.py anima\sylanne_alpha\personality_drift_viewer.py anima\sylanne_alpha\scar_explorer.py anima\sylanne_alpha\desire_dashboard.py anima\sylanne_alpha\memory_explorer.py anima\sylanne_alpha\state_inspector.py anima\sylanne_alpha\state_persistence.py anima\sylanne_alpha\llm_request_pipeline.py anima\sylanne_alpha\webui_routes.py anima\sylanne_alpha\webui_server.py main.py plugin_api.py anima\mixins\desire.py
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
- Memory Recall Replay redaction for memory text, query text, prompt bodies, and unsafe runtime event payloads
- `memory.recall_performed` runtime event metadata for recall-chain observability
- shared WebUI and independent WebUI `/api/memory_recall_replay` route registration
- Portal Memory Recall Replay card/API hook contract
- Desire Dashboard redaction for desire content, target UMO, and target user identifiers
- shared WebUI and independent WebUI `/api/desire_dashboard` route registration
- Portal Desire Dashboard card/API hook contract
- Desire Evolution History redaction for desire content, targets, and unsafe runtime event payloads
- enhanced `desire.queue_updated` queue-diff metadata for lifecycle observability
- shared WebUI and independent WebUI `/api/desire_evolution` route registration
- Portal Desire Evolution card/API hook contract
- Scar Explorer redaction for scar source text and legacy raw fields
- shared WebUI and independent WebUI `/api/scar_explorer` route registration
- Portal Scar Explorer card/API hook contract
- Personality Drift Viewer redaction for persona_core text and mutation descriptions
- shared WebUI and independent WebUI `/api/personality_drift` route registration
- Portal Personality Drift card/API hook contract
- Reasoning Trace redaction for prompt text, tool argument values, tool results, and response text
- tool invocation runtime event metadata for traceability
- shared WebUI and independent WebUI `/api/reasoning_trace` route registration
- Portal Reasoning Trace card/API hook contract
- Portal normal-load refresh coverage for Scar Explorer and Personality Drift cards
- Session Replay redaction for user text, bot text, prompt text, tool argument values, and tool results
- shared WebUI and independent WebUI `/api/session_replay` route registration
- Portal Session Replay card/API hook contract
- unified AstrBot Plugin Page entry contract (`pages/anima` only)
- legacy dashboard/capability-tree assets preserved under internal WebUI assets
- standalone WebUI legacy route asset directory wiring

## Latest Result

- `py -3 -m py_compile ...`: passed
- `node -e "... vm.Script(...portal script ...)"`: passed
- `py -3 -m pytest tests\test_memory_recall_replay.py tests\test_memory_explorer.py tests\test_cognitive_timeline_webui.py tests\test_session_replay.py tests\test_reasoning_trace.py -q`: `18 passed`
- `py -3 -m pytest tests\test_desire_evolution.py tests\test_desire_dashboard.py tests\test_cognitive_timeline_webui.py tests\test_phase2_stability_fixes.py -q`: `19 passed`
- `py -3 -m pytest tests\test_desire_evolution.py tests\test_desire_dashboard.py tests\test_cognitive_timeline_webui.py tests\test_runtime_observability.py tests\test_unified_plugin_page.py -q`: `20 passed`
- `py -3 -m pytest tests\test_unified_plugin_page.py -q`: `3 passed`
- `py -3 -m pytest tests\test_session_replay.py tests\test_reasoning_trace.py tests\test_cognitive_timeline_webui.py tests\test_runtime_observability.py -q`: `18 passed`
- `py -3 -m pytest tests\test_reasoning_trace.py tests\test_cognitive_timeline_webui.py tests\test_runtime_observability.py -q`: `15 passed`
- `py -3 -m pytest tests\test_desire_dashboard.py tests\test_cognitive_timeline_webui.py -q`: `7 passed`
- `py -3 -m pytest tests\test_scar_explorer.py tests\test_cognitive_timeline_webui.py -q`: `8 passed`
- `py -3 -m pytest tests\test_personality_drift_viewer.py tests\test_cognitive_timeline_webui.py -q`: `9 passed`
- `py -3 -m pytest tests\test_memory_explorer.py tests\test_cognitive_timeline_webui.py -q`: `6 passed`
- `py -3 -m pytest tests\test_state_inspector.py tests\test_cognitive_timeline_webui.py -q`: `5 passed`
- `py -3 -m pytest tests\test_cognitive_timeline_webui.py tests\test_runtime_observability.py -q`: `7 passed`
- `py -3 -m pytest tests\test_runtime_observability.py tests\test_phase2_stability_fixes.py -q`: `9 passed`
- `py -3 -m pytest -q`: `384 passed, 50 warnings`

## Warnings

The remaining warnings are existing `DeprecationWarning: __package__ != __spec__.parent` warnings emitted while importing `main.py` in the test environment. They do not fail the suite and were not introduced by the Runtime Event Bus behavior.
