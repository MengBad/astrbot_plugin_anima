# Release Notes - v1.2.4

## Summary

v1.2.4 is a stability and observability release for `astrbot_plugin_anima`.
It focuses on release-readiness rather than new cognitive behavior:

- safer state persistence
- stronger shutdown cleanup
- consistent Sylanne response observation
- lower-risk JSON serialization compatibility
- first foundation of the Cognitive Observatory through a Runtime Event Bus and JSONL Cognitive Timeline

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

Recommended tag: `v1.2.4`

Release type: patch release.

Reason: the work fixes stability, data consistency, lifecycle, and observability issues without changing public cognitive semantics.
