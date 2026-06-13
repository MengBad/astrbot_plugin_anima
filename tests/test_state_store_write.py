"""StateStore 写入混合类测试。"""

import asyncio
import json
import os
import tempfile

import pytest

from anima.state_store import StateStore, StateStoreWriteMixin, JsonStateSource


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


class MockPlugin(StateStoreWriteMixin):
    """模拟插件类，用于测试 StateStoreWriteMixin。"""

    def __init__(self, data_dir: str):
        self._data_dir = data_dir
        self.self_notes_path = os.path.join(data_dir, "self_notes.md")
        self._io_lock = None
        super().__init__()
        self._init_state_store(data_dir)


def test_init_state_store(tmp_dir):
    plugin = MockPlugin(tmp_dir)
    assert plugin._state_store is not None
    assert "self_notes" in plugin._state_store.source_names


def test_write_and_read_self_notes(tmp_dir):
    plugin = MockPlugin(tmp_dir)
    asyncio.run(plugin._write_self_notes("# Test Notes"))
    result = asyncio.run(plugin._read_self_notes())
    assert result == "# Test Notes"


def test_write_and_read_desires(tmp_dir):
    plugin = MockPlugin(tmp_dir)
    data = {"desires": [{"content": "test", "intensity": 0.5}]}
    asyncio.run(plugin._write_desires(data))
    result = asyncio.run(plugin._read_desires())
    assert result == data


def test_write_and_read_state(tmp_dir):
    plugin = MockPlugin(tmp_dir)
    data = {"personality_vector": [0.1, 0.2, 0.3]}
    asyncio.run(plugin._write_state_data(data))
    result = asyncio.run(plugin._read_state_data())
    assert result == data


def test_read_nonexistent_returns_empty(tmp_dir):
    plugin = MockPlugin(tmp_dir)
    result = asyncio.run(plugin._read_self_notes())
    assert result == ""


def test_read_nonexistent_desires_returns_empty(tmp_dir):
    plugin = MockPlugin(tmp_dir)
    result = asyncio.run(plugin._read_desires())
    assert result == {}
