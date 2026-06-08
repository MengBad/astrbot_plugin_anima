# Migration Guide - v1.2.4

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
/astrbot_plugin_anima/api/memory_explorer
/astrbot_plugin_anima/api/memory_recall_replay
/astrbot_plugin_anima/api/desire_dashboard
/astrbot_plugin_anima/api/desire_evolution
/astrbot_plugin_anima/api/scar_explorer
/astrbot_plugin_anima/api/personality_drift
/astrbot_plugin_anima/api/reasoning_trace
/astrbot_plugin_anima/api/session_replay
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
Desire Evolution History is observability-only too: it connects current desire queue metadata with recent queue update events without exposing desire text, target UMO values, target users, or arbitrary runtime-event payload values.

## Recommended Operator Checks

After upgrading:

1. Restart or reload the plugin.
2. Confirm `/astrbot_plugin_anima/health` responds if WebUI routes are enabled.
3. Open `/astrbot_plugin_anima/api/runtime_events?limit=20`.
4. If using the independent WebUI, open `/api/runtime_events?limit=20&token=<token>`.
5. Open Anima Portal and check the `Cognitive Timeline` panel.
6. Check that `Reasoning Trace`, `Session Replay`, `State Inspector`, `Memory Explorer`, `Memory Recall Replay`, `Desire Dashboard`, `Desire Evolution`, `Scar Explorer`, and `Personality Drift` cards render in the same panel.
7. Run one normal conversation turn.
8. Confirm a `response.observed` event appears.
9. If a tool is used, confirm `tool.invocation_started` / `tool.invocation_finished` metadata appears without raw arguments or results.
10. Check logs for any `corrupt-json` backup notices.

## Rollback

Rollback to the previous plugin version is safe.

If `.bak` files were created for corrupt JSON, keep them for manual inspection. They are not required by v1.2.4 at runtime.
