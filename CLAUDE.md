# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Anima (Autonomous Narrative Memory Engine / 自主叙事记忆引擎) is an AstrBot plugin that gives AI roleplay characters autonomous narrative memory, self-awareness, stance evolution, and personality drift. It builds three layers: **relationships** (SylannEngine), **self-identity** (core Anima), and **desire** (autonomous intent).

- Requires AstrBot >= v4.25
- Runtime dependency: only `aiohttp>=3.9.0`
- Latest version: 1.2.1

## Commands

```bash
# Run all tests (configured in pytest.ini: -v --tb=short)
pytest

# Run a single test file
pytest tests/test_filters.py

# Run a single test
pytest tests/test_filters.py::test_function_name

# Install dev dependencies
pip install -r requirements-dev.txt
```

No build step — this is a Python plugin loaded directly by AstrBot.

## Architecture

### Dual-Layer Design

The codebase has a strict separation between two layers:

1. **Pure functions** (`anima/*.py`) — stateless, independently testable modules: `filters.py`, `similarity.py`, `capability_dedup.py`, `forgetting.py`, `valence.py`
2. **Mixin classes** (`anima/mixins/*.py`) — 18 mixins that depend on plugin `self.*` state, composed via **multiple inheritance** into `AnimaPlugin` in `main.py`

When adding new functionality, determine which layer it belongs to. Pure logic goes in `anima/`; stateful behavior that needs plugin context goes in `anima/mixins/`.

### SylannEngine Integration

`anima/sylanne_alpha/` is a deep integration of SylannEngine (by Ayleovelle), providing relationship physics via Scar Algebra and Void Calculus. In live environments, mixins dynamically route to SylannEngine. In automated tests, a Mock fallback activates so the plugin can run independently.

### Key Files

- **`main.py`** (~2186 lines) — `AnimaPlugin` class with all AstrBot hooks and slash commands
- **`plugin_api.py`** — Web API routes for Plugin Pages (dashboard, stats)
- **`_conf_schema.json`** — AstrBot WebUI configuration schema
- **`metadata.yaml`** — AstrBot plugin registration metadata

### Async Pattern

Sedimentation (the core memory-writing flow) runs via `asyncio.create_task` and never blocks the main conversation. All LLM calls have timeouts: emotion 15s, monologue 30s, compression 60s, Sylanne 5s, merged calls 15s.

### Three-Layer World Model

1. **Relationships** (SylannEngine) — scar accumulation, void growth, pressure transmission
2. **Self-identity** (Anima core) — self_notes, personality vector (5-dim EMA), worldview
3. **Desire** (Anima desire system) — autonomous intent that grows from within, decays over time

### Data Storage

All runtime data lives under `data/plugin_data/astrbot_plugin_anima/` (gitignored). Key files: `self_notes.md` (human-readable), `evolution_log.jsonl`, `anima_state.json`, `persona_core.yaml`, `social_graph.json`. Session-isolated data (worldview, time_sense) lives under `sessions/<umo>/`.

## Conventions

- **Language**: Code identifiers are in English. Comments, config descriptions, and user-facing strings are in Chinese.
- **Testing**: Uses pytest + Hypothesis for property-based tests. Test host stubs (`_cap_host.py`, `_danger_host.py`, `_merged_eval_host.py`) provide mock plugin state.
- **Degradation**: Every optional module fails silently — vector memory unavailable, Sylanne missing, any module error — core functionality is never blocked.
- **Config toggles**: Most features are off by default. High-danger features (`danger_*`) require explicit enablement; some require a `_confirm` secondary toggle.
