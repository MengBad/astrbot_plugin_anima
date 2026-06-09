# Migration Guide - v1.2.5

## Who Needs Action?

Most users do not need any manual migration.

This release is designed to be backward compatible with existing Anima and Sylanne state files.

## What Changed Operationally?

### Atomic persistence

State writes now use safer temporary-file replacement for key JSON/text files.

If a state file is found to be corrupt during an atomic update, Anima will:

1. skip the destructive write
2. move the corrupt file to a timestamped `.bak`
3. continue running with safe defaults where possible

### Runtime Event Bus

A new Runtime Event Bus records structured observability events in memory and appends them to a JSONL timeline.
Events are also appended to:

```text
data/plugin_data/astrbot_plugin_anima/runtime_events.jsonl
```

New API:

```text
/astrbot_plugin_anima/api/runtime_events
```

Additional redacted Observatory APIs are also available in this release line:

```text
/astrbot_plugin_anima/api/prompt_debug
/astrbot_plugin_anima/api/state_inspector
/astrbot_plugin_anima/api/state_store_audit
/astrbot_plugin_anima/api/background_tasks
/astrbot_plugin_anima/api/memory_explorer
/astrbot_plugin_anima/api/memory_recall_replay
/astrbot_plugin_anima/api/desire_dashboard
/astrbot_plugin_anima/api/desire_evolution
/astrbot_plugin_anima/api/scar_explorer
/astrbot_plugin_anima/api/personality_drift
/astrbot_plugin_anima/api/reasoning_trace
/astrbot_plugin_anima/api/session_replay
/astrbot_plugin_anima/api/mutation_history
```

Optional query parameters:

```text
limit=100
session=<session_key>
type=<event_type>
severity=<severity>
```

This is an observability feature only. It does not change prompt assembly, memory retrieval, personality drift, scar algebra, or desire formation.
Reasoning Trace is also observability-only: it assembles prompt/tool/response decision metadata without storing prompt text, memory bodies, tool argument values, tool results, or response text.
Session Replay is observability-only as well: it merges event metadata and conversation-buffer message shapes without exposing message text.
Memory Recall Replay is observability-only too: it reads existing recall evidence and prompt-debug metadata without triggering memory recall or changing memory weights.
Background Task Observatory is observability-only too: it reads task and queue metadata without cancelling, scheduling, retrying, or mutating background work.
Desire Evolution History is observability-only too: it connects current desire queue metadata with recent queue update events without exposing desire text, target UMO values, target users, or arbitrary runtime-event payload values.
Mutation History is observability-only too: it exposes schema-versioned, redacted mutation metadata with length/fingerprint evidence instead of raw mutation descriptions.

StateStore Audit is observability-only too: it is available as `/api/state_store_audit`, also embedded inside `/api/state_inspector` as `anima.state_store_audit.v1`, and reports only state-source metadata, runtime container counts, session-file aggregate counts, KV availability, future StateStore capability gaps, and metadata-only fingerprints for diff readiness.
Those fingerprints are based on source metadata such as basename, existence, size, and mtime. They are not content hashes and do not read state bodies.

### Background task lifecycle registry

Anima now normalizes legacy list-style and newer set-style `_background_tasks` containers into one compatible registry at runtime.
This is an internal lifecycle consistency fix only. It does not change user-facing configuration, memory data, prompt assembly, Sylanne state files, or WebUI API schemas.

## Recommended Operator Checks

After upgrading:

1. Restart or reload the plugin.
2. Confirm `/astrbot_plugin_anima/health` responds if WebUI routes are enabled.
3. Open `/astrbot_plugin_anima/api/runtime_events?limit=20`.
4. If using the independent WebUI, open `/api/runtime_events?limit=20&token=<token>`.
5. Open Anima Portal and check the `Cognitive Timeline` panel.
6. Check that `Reasoning Trace`, `Session Replay`, `State Inspector`, `Background Tasks`, `Memory Explorer`, `Memory Recall Replay`, `Desire Dashboard`, `Desire Evolution`, `Scar Explorer`, and `Personality Drift` cards render in the same panel.
7. If opening from AstrBot's Plugin Page list, confirm network requests use `/astrbot_plugin_anima/api/...`; if opening the independent Sylanne WebUI, confirm requests still use `/api/...`.
8. In the unified Portal, open the Dashboard and Capability Tree iframe tabs and confirm their internal API calls resolve under `/astrbot_plugin_anima/...` on the shared WebUI path.
9. Run one normal conversation turn.
10. Confirm a `response.observed` event appears.
11. If a tool is used, confirm `tool.invocation_started` / `tool.invocation_finished` metadata appears without raw arguments or results.
12. Check logs for any `corrupt-json` backup notices.

## Rollback

Rollback to the previous plugin version is safe.

If `.bak` files were created for corrupt JSON, keep them for manual inspection. They are not required by v1.2.5 at runtime.
