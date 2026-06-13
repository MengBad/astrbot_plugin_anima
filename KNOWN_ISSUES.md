# Known Issues - v1.3.0

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
However, the full Observatory is not complete yet. Runtime Timeline, Prompt Debugger API, State Inspector API/card, Background Tasks API/card, Memory Explorer API/card, Memory Recall Replay API/card, Desire Dashboard API/card, Desire Evolution API/card, Scar Explorer API/card, Personality Drift API/card, Reasoning Trace API/card, Session Replay API/card, and redacted Mutation History exist, but the Portal still lacks deeper drill-down and compare tools for long-horizon cognitive trends.

Next step:

- add cross-session trend comparison and StateStore-backed audit views incrementally

### Some persistence paths remain outside a unified StateStore

`anima_state.json`, `self_notes.md`, `desires.json`, Sylanne runtime files, runtime caches, and AstrBot KV are still separate state sources.

State Inspector now embeds a read-only `anima.state_store_audit.v1` inventory so operators can see the current topology and missing StateStore capabilities. It also exposes metadata-only fingerprints for diff readiness, including declared-but-unconfigured sources, runtime containers, and session-file aggregate counts, but it is not a write path and does not provide content snapshot/diff/rollback yet.

Next step:

- introduce `StateStore` as an abstraction layer supporting snapshot, diff, rollback, audit, and timeline

### 50 DeprecationWarning during test execution

The test suite emits 50 `DeprecationWarning: __package__ != __spec__.parent` warnings when importing `main.py` in the test environment.

Impact:

- does not affect runtime behavior
- does not fail the test suite
- caused by Python 3.14 import system changes

Next step:

- will resolve when AstrBot core updates its import mechanism or when Python stabilizes the import system
