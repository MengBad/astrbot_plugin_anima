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

Optional query parameters:

```text
limit=100
session=<session_key>
type=<event_type>
severity=<severity>
```

This is an observability feature only. It does not change prompt assembly, memory retrieval, personality drift, scar algebra, or desire formation.

## Recommended Operator Checks

After upgrading:

1. Restart or reload the plugin.
2. Confirm `/astrbot_plugin_anima/health` responds if WebUI routes are enabled.
3. Open `/astrbot_plugin_anima/api/runtime_events?limit=20`.
4. If using the independent WebUI, open `/api/runtime_events?limit=20&token=<token>`.
5. Open Anima Portal and check the `Cognitive Timeline` panel.
6. Run one normal conversation turn.
7. Confirm a `response.observed` event appears.
8. Check logs for any `corrupt-json` backup notices.

## Rollback

Rollback to the previous plugin version is safe.

If `.bak` files were created for corrupt JSON, keep them for manual inspection. They are not required by v1.2.4 at runtime.
