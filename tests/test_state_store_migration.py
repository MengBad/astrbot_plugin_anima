"""StateStore 迁移助手测试。"""

import asyncio
import json
import os
import tempfile

import pytest

from anima.state_store import StateStore, JsonStateSource, MarkdownStateSource, JsonlStateSource
from anima.state_store.migration import register_legacy_sources, get_store_summary


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def store(tmp_dir):
    return StateStore(data_dir=tmp_dir)


def test_register_legacy_sources(store, tmp_dir):
    # 创建一些测试文件
    with open(os.path.join(tmp_dir, "anima_state.json"), "w") as f:
        json.dump({"test": "state"}, f)
    with open(os.path.join(tmp_dir, "self_notes.md"), "w") as f:
        f.write("# Test Notes")
    with open(os.path.join(tmp_dir, "evolution_log.jsonl"), "w") as f:
        f.write('{"type": "test"}\n')

    # 注册旧源
    register_legacy_sources(store, tmp_dir)

    # 验证注册成功
    assert "anima_state" in store.source_names
    assert "self_notes" in store.source_names
    assert "evolution_log" in store.source_names
    # 10 JSON + 3 Markdown + 2 JSONL = 15 total
    assert len(store.source_names) == 15


def test_register_legacy_sources_read(store, tmp_dir):
    # 创建测试文件
    with open(os.path.join(tmp_dir, "anima_state.json"), "w") as f:
        json.dump({"personality_vector": [0.1, 0.2, 0.3]}, f)

    register_legacy_sources(store, tmp_dir)

    # 读取数据
    source = store.get_source("anima_state")
    assert source is not None
    data = asyncio.run(source.read())
    assert data == {"personality_vector": [0.1, 0.2, 0.3]}


def test_get_store_summary(store, tmp_dir):
    register_legacy_sources(store, tmp_dir)
    summary = get_store_summary(store)

    assert summary["total_sources"] > 0
    assert "anima_state" in summary["sources"]
    assert summary["snapshots"] == []
