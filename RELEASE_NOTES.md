# Release Notes - v1.2.5

## Summary

v1.2.5 is a stability and observability release for `astrbot_plugin_anima`.
It focuses on release-readiness rather than new cognitive behavior:

- safer state persistence
- stronger shutdown cleanup
- consistent Sylanne response observation
- lower-risk JSON serialization compatibility
- first foundation of the Cognitive Observatory through a Runtime Event Bus and JSONL Cognitive Timeline
- redacted Prompt Debugger snapshots for prompt-injection budget observability
- redacted State Inspector snapshots for session/state consistency observability
- redacted Memory Explorer snapshots for three-layer memory topology observability
- redacted Desire Dashboard snapshots for desire queue and autonomy-drive observability
- redacted Scar Explorer snapshots for Scar Algebra and legacy scar-source observability
- redacted Personality Drift Viewer snapshots for personality continuity observability

The release preserves the dual-engine architecture:

- legacy Anima Mixin paths remain available
- Sylanne Alpha hot path remains intact
- high-risk autonomy logic is not simplified or removed

## Highlights

- Corrupt `anima_state.json` is now backed up instead of being overwritten by `{}`.
- Core JSON/text writes use temp-file + `os.replace` atomic persistence.
- `desires.json` updates can use a single transactional update boundary.
- Bot responses are observed even when realtime intercept is disabled.
- Plugin termination flushes loaded Sylanne hosts and cancels tracked background tasks.
- JSONEncoder monkeypatch is now idempotent and restored on terminate.
- `/astrbot_plugin_anima/api/runtime_events` exposes structured runtime events.
- Runtime events are appended to `data/plugin_data/astrbot_plugin_anima/runtime_events.jsonl`.
- `/astrbot_plugin_anima/events` now prefers Runtime Event Bus data and falls back to evolution logs.
- Anima Portal now includes a `Cognitive Timeline` panel for live runtime event inspection.
- The independent Sylanne WebUI server also exposes `/api/runtime_events`.
- `/api/prompt_debug` is available on both WebUI layers for redacted prompt injection snapshots.
- Prompt debugger snapshots record slot names, raw/trimmed lengths, budget, and injection path, but never store full prompt text or memory bodies.
- `/api/state_inspector` is available on both WebUI layers for redacted session/state topology snapshots.
- State Inspector snapshots expose dirty subsystems, persistence file metadata, host/memory/buffer presence, KV availability, and session isolation diagnostics without reading self notes, desire content, or memory bodies.
- The Anima Portal Cognitive Timeline panel now includes a State Inspector card so operators can inspect session/state topology without leaving the Observatory view.
- `/api/memory_explorer` is available on both WebUI layers for redacted L1/L2/L3 memory topology snapshots.
- Memory Explorer snapshots expose counts, recall/rewrite metadata, embedding presence, selected memory parameters, and SHA fingerprints without exposing memory text or graph labels.
- The Anima Portal Cognitive Timeline panel now includes a Memory Explorer card for quick memory topology inspection.
- `/api/desire_dashboard` is available on both WebUI layers for redacted desire queue snapshots.
- Desire Dashboard snapshots expose queue health, source/kind/intensity distributions, scoped-target signals, and hashes without exposing desire content or target identifiers.
- The Anima Portal Cognitive Timeline panel now includes a Desire Dashboard card for quick autonomy-drive inspection.
- `/api/scar_explorer` is available on both WebUI layers for redacted scar topology snapshots.
- Scar Explorer snapshots expose Sylanne Scar Algebra session state, healing stages, dimension sensitivities, circuit breakers, session cap pressure, and legacy JSON scar-source counts without exposing raw scar source text.
- The Anima Portal Cognitive Timeline panel now includes a Scar Explorer card for quick trauma/repair topology inspection.
- `/api/personality_drift` is available on both WebUI layers for redacted personality continuity snapshots.
- Personality Drift snapshots expose legacy 5D vectors, Sylanne Embodiment Five EMA/set-point state, surface traits, drift attribution counts, relationship-delta counts, mutation metadata hashes, and persona-core fingerprints without exposing persona_core text or mutation descriptions.
- The Anima Portal Cognitive Timeline panel now includes a Personality Drift card for quick人格连续性 inspection.

## Compatibility

No migration is required for normal users.

Existing files remain compatible:

- `anima_state.json`
- `self_notes.md`
- `desires.json`
- Sylanne `.alpha.json` runtime files
- AstrBot KV state

If a corrupt JSON file is detected, it is moved to a timestamped `.bak` file so operators can inspect or restore it manually.

## Release Recommendation

Recommended tag: `v1.2.5`

Release type: patch release.

Reason: the work fixes stability, data consistency, lifecycle, and observability issues without changing public cognitive semantics.
