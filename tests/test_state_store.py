"""StateStore 统一状态存储测试。"""

import asyncio
import json
import os
import tempfile

import pytest

from anima.state_store import (
    StateStore,
    StateSource,
    JsonStateSource,
    MarkdownStateSource,
    JsonlStateSource,
    Snapshot,
    Diff,
    Change,
)


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def store(tmp_dir):
    return StateStore(data_dir=tmp_dir)


class TestJsonStateSource:
    def test_read_nonexistent(self, tmp_dir):
        source = JsonStateSource(os.path.join(tmp_dir, "nonexistent.json"), "test")
        result = asyncio.run(source.read())
        assert result == {}

    def test_write_and_read(self, tmp_dir):
        path = os.path.join(tmp_dir, "test.json")
        source = JsonStateSource(path, "test")
        data = {"key": "value", "nested": {"a": 1}}

        asyncio.run(source.write(data))
        result = asyncio.run(source.read())

        assert result == data

    def test_metadata(self, tmp_dir):
        path = os.path.join(tmp_dir, "test.json")
        source = JsonStateSource(path, "test", scope="global", role="state")

        asyncio.run(source.write({"a": 1}))
        meta = asyncio.run(source.metadata())

        assert meta["name"] == "test"
        assert meta["exists"] is True
        assert meta["scope"] == "global"
        assert meta["format"] == "json"
        assert meta["role"] == "state"


class TestMarkdownStateSource:
    def test_read_nonexistent(self, tmp_dir):
        source = MarkdownStateSource(os.path.join(tmp_dir, "nonexistent.md"), "test")
        result = asyncio.run(source.read())
        assert result == ""

    def test_write_and_read(self, tmp_dir):
        path = os.path.join(tmp_dir, "test.md")
        source = MarkdownStateSource(path, "test")
        content = "# Hello\n\nThis is a test."

        asyncio.run(source.write(content))
        result = asyncio.run(source.read())

        assert result == content


class TestJsonlStateSource:
    def test_read_nonexistent(self, tmp_dir):
        source = JsonlStateSource(os.path.join(tmp_dir, "nonexistent.jsonl"), "test")
        result = asyncio.run(source.read())
        assert result == []

    def test_append_and_read(self, tmp_dir):
        path = os.path.join(tmp_dir, "test.jsonl")
        source = JsonlStateSource(path, "test")

        asyncio.run(source.append({"id": 1, "type": "a"}))
        asyncio.run(source.append({"id": 2, "type": "b"}))
        result = asyncio.run(source.read())

        assert len(result) == 2
        assert result[0]["id"] == 1
        assert result[1]["id"] == 2


class TestStateStore:
    def test_register_source(self, store, tmp_dir):
        source = JsonStateSource(os.path.join(tmp_dir, "test.json"), "test")
        store.register_source("test", source)

        assert "test" in store.source_names
        assert store.get_source("test") is source

    def test_unregister_source(self, store, tmp_dir):
        source = JsonStateSource(os.path.join(tmp_dir, "test.json"), "test")
        store.register_source("test", source)
        store.unregister_source("test")

        assert "test" not in store.source_names

    def test_snapshot(self, store, tmp_dir):
        source = JsonStateSource(os.path.join(tmp_dir, "test.json"), "test")
        store.register_source("test", source)

        asyncio.run(source.write({"key": "value"}))
        snapshot = asyncio.run(store.snapshot("snap1"))

        assert snapshot.name == "snap1"
        assert snapshot.data["test"] == {"key": "value"}

    def test_diff(self, store, tmp_dir):
        source = JsonStateSource(os.path.join(tmp_dir, "test.json"), "test")
        store.register_source("test", source)

        asyncio.run(source.write({"key": "old"}))
        old_snapshot = asyncio.run(store.snapshot("old"))

        asyncio.run(source.write({"key": "new"}))
        new_snapshot = asyncio.run(store.snapshot("new"))

        diff = asyncio.run(store.diff(old_snapshot, new_snapshot))

        assert diff.has_changes
        assert len(diff.changes) == 1
        assert diff.changes[0].key == "test"

    def test_rollback(self, store, tmp_dir):
        source = JsonStateSource(os.path.join(tmp_dir, "test.json"), "test")
        store.register_source("test", source)

        asyncio.run(source.write({"key": "original"}))
        original_snapshot = asyncio.run(store.snapshot("original"))

        asyncio.run(source.write({"key": "modified"}))
        current = asyncio.run(source.read())
        assert current["key"] == "modified"

        asyncio.run(store.rollback(original_snapshot))
        restored = asyncio.run(source.read())
        assert restored["key"] == "original"

    def test_metadata(self, store, tmp_dir):
        source = JsonStateSource(os.path.join(tmp_dir, "test.json"), "test")
        store.register_source("test", source)

        meta = asyncio.run(store.metadata())

        assert meta["source_count"] == 1
        assert "test" in meta["sources"]


class TestSnapshotDataClass:
    def test_to_dict(self):
        snapshot = Snapshot(name="test", data={"a": 1, "b": "hello"})
        d = snapshot.to_dict()

        assert d["name"] == "test"
        assert "a" in d["data_keys"]
        assert "b" in d["data_keys"]


class TestDiffDataClass:
    def test_has_changes(self):
        diff = Diff(changes=[Change(key="a", old=1, new=2)])
        assert diff.has_changes

    def test_no_changes(self):
        diff = Diff()
        assert not diff.has_changes

    def test_to_dict(self):
        diff = Diff(changes=[Change(key="a", old=1, new=2)])
        d = diff.to_dict()

        assert d["change_count"] == 1
        assert d["changes"][0]["key"] == "a"
