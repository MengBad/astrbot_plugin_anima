# Known Issues - v1.2.4 Release Candidate

## Remaining Risks

### Runtime Event Timeline is not yet a full StateStore

Runtime events are now appended to `runtime_events.jsonl` and loaded into an in-memory ring buffer on startup.

Impact:

- timeline persistence is append-only JSONL
- no snapshot/diff/rollback semantics yet
- no compaction or retention policy beyond the in-memory query window

Next step:

- connect Runtime Event Bus to the future unified `StateStore` with snapshot/diff/rollback/audit support

### Host creation is still synchronous lazy initialization

Sylanne host creation remains a synchronous lazy path.

Impact:

- normal asyncio request flow is safe because there is no `await` inside the critical creation block
- deeper multi-threaded or unusual host access patterns could still benefit from a dedicated host initialization guard

Next step:

- add explicit session-scoped host init guard once StateStore work begins

### JSONEncoder monkeypatch still exists

The global JSONEncoder patch is now idempotent and restorable, but it remains a global compatibility workaround.

Impact:

- lower risk than before, but still broader than ideal

Next step:

- replace with local serialization adapters once AstrBot core compatibility allows it

### Cognitive Observatory UI is still incomplete

The Portal now renders a Cognitive Timeline panel backed by runtime events.
However, the full Observatory is not complete yet. Runtime Timeline, Prompt Debugger API, State Inspector API/card, Memory Explorer API/card, Memory Recall Replay API/card, Desire Dashboard API/card, Desire Evolution API/card, Scar Explorer API/card, Personality Drift API/card, Reasoning Trace API/card, and Session Replay API/card exist, but the Portal still lacks deeper drill-down and compare tools for long-horizon cognitive trends.

Next step:

- add cross-session trend comparison and StateStore-backed audit views incrementally

### Some persistence paths remain outside a unified StateStore

`anima_state.json`, `self_notes.md`, `desires.json`, Sylanne runtime files, runtime caches, and AstrBot KV are still separate state sources.

Next step:

- introduce `StateStore` as an abstraction layer supporting snapshot, diff, rollback, audit, and timeline
