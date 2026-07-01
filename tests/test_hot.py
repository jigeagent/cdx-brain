#!/usr/bin/env python3
"""Tests for cdx_brain.hot module.

Covers: read, write, clear, front-matter parsing, expiry, truncation,
disabled config, missing file, empty file, error handling.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import pytest

_REPO = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(_REPO))

from cdx_brain.hot import (
    read_hot,
    write_hot,
    clear_hot,
    _parse_front_matter,
    _is_expired,
    _build_hot_content,
    _truncate,
    _resolve_config,
)


# ── Fixtures ──


@pytest.fixture
def tmp_hot() -> tuple[str, dict[str, Any]]:
    """Return (hot_path, config) pointing at a temporary empty directory."""
    d = tempfile.mkdtemp()
    hot_path = os.path.join(d, "hot.md")
    cfg: dict[str, Any] = {
        "memory": {
            "hot": {
                "enabled": True,
                "path": hot_path,
                "max_age_hours": 24,
                "max_tokens": 500,
            }
        }
    }
    yield hot_path, cfg
    # cleanup
    try:
        os.remove(hot_path)
    except OSError:
        pass
    try:
        os.rmdir(d)
    except OSError:
        pass


# ── _parse_front_matter ──


class TestParseFrontMatter:
    def test_basic(self) -> None:
        text = "---\nkey: value\nfoo: bar\n---\nbody"
        result = _parse_front_matter(text)
        assert result == {"key": "value", "foo": "bar"}

    def test_no_front_matter(self) -> None:
        text = "just body content\nno markers"
        result = _parse_front_matter(text)
        assert result == {}

    def test_missing_closing_marker(self) -> None:
        text = "---\nkey: val\nno closing"
        result = _parse_front_matter(text)
        assert result == {}

    def test_empty(self) -> None:
        assert _parse_front_matter("") == {}

    def test_only_markers(self) -> None:
        assert _parse_front_matter("---\n---") == {}

    def test_multiline_values(self) -> None:
        text = "---\ntitle: hello world\ndone: true\n---"
        result = _parse_front_matter(text)
        assert result["title"] == "hello world"
        assert result["done"] == "true"


# ── _build_hot_content ──


class TestBuildHotContent:
    def test_minimal(self) -> None:
        content = _build_hot_content({})
        assert "---" in content
        assert "updated_at" in content
        assert "status: in_progress" in content

    def test_full_state(self) -> None:
        content = _build_hot_content({
            "project": "cdx-brain",
            "status": "blocked",
            "blocked": "waiting for review",
            "summary": "integration done",
            "next": "add tests",
            "todos": [
                {"text": "write tests", "done": False},
                {"text": "review", "done": True},
            ],
        })
        assert "project: cdx-brain" in content
        assert "status: blocked" in content
        assert "blocked: waiting for review" in content
        assert "summary: integration done" in content
        assert "next: add tests" in content
        assert "- [ ] write tests" in content
        assert "- [x] review" in content

    def test_no_todos_when_empty(self) -> None:
        content = _build_hot_content({"summary": "test"})
        assert "## 待办" not in content


# ── _is_expired ──


class TestIsExpired:
    def test_past(self) -> None:
        assert _is_expired("2020-01-01T00:00:00+00:00", 24) is True

    def test_future(self) -> None:
        assert _is_expired("2099-01-01T00:00:00+00:00", 24) is False

    def test_invalid_string(self) -> None:
        assert _is_expired("not-a-date", 24) is False

    def test_empty_string(self) -> None:
        assert _is_expired("", 24) is False


# ── _truncate ──


class TestTruncate:
    def test_short_text(self) -> None:
        text = "short"
        assert _truncate(text, 500) == text

    def test_long_text(self) -> None:
        text = "a" * 5000  # ~1250 tokens at 4 chars/token
        result = _truncate(text, 100)  # 100 tokens = 400 chars
        assert len(result) <= 420  # 400 + "...(truncated)"
        assert result.endswith("...(truncated)")

    def test_empty(self) -> None:
        assert _truncate("", 100) == ""
        assert _truncate(None, 100) == ""


# ── _resolve_config ──


class TestResolveConfig:
    def test_defaults(self) -> None:
        cfg = _resolve_config(None)
        assert cfg["enabled"] is True
        assert cfg["max_age_hours"] == 24
        assert cfg["max_tokens"] == 500

    def test_custom(self) -> None:
        cfg = _resolve_config({
            "memory": {
                "hot": {
                    "enabled": False,
                    "path": "/custom/path.md",
                    "max_age_hours": 48,
                }
            }
        })
        assert cfg["enabled"] is False
        assert cfg["path"] == "/custom/path.md"
        assert cfg["max_age_hours"] == 48
        assert cfg["max_tokens"] == 500  # default inherited


# ── Integration: write / read / clear ──


class TestWriteReadClear:
    def test_write_and_read(self, tmp_hot: Any) -> None:
        hot_path, config = tmp_hot
        ok = write_hot({
            "project": "test-project",
            "status": "done",
            "summary": "wrote tests",
            "next": "commit",
            "blocked": "",
        }, config)
        assert ok is True

        state = read_hot(config)
        assert state is not None
        assert state["project"] == "test-project"
        assert state["status"] == "done"
        assert state["summary"] == "wrote tests"
        assert state["next"] == "commit"
        assert state["blocked"] == ""
        assert state["expired"] is False

    def test_clear(self, tmp_hot: Any) -> None:
        hot_path, config = tmp_hot
        write_hot({"project": "p", "summary": "s"}, config)
        assert read_hot(config) is not None
        clear_hot(config)
        assert read_hot(config) is None

    def test_missing_file(self, tmp_hot: Any) -> None:
        hot_path, config = tmp_hot
        # Path doesn't exist yet
        state = read_hot(config)
        assert state is None

    def test_disabled(self) -> None:
        cfg: dict[str, Any] = {"memory": {"hot": {"enabled": False}}}
        assert read_hot(cfg) is None
        assert write_hot({"project": "x"}, cfg) is False
        assert clear_hot(cfg) is False

    def test_read_expired(self, tmp_hot: Any) -> None:
        hot_path, config = tmp_hot
        # Write a hot.md with a very old timestamp
        old_content = (
            "---\n"
            "updated_at: 2020-01-01T00:00:00+00:00\n"
            "project: old\n"
            "status: done\n"
            "summary: ancient\n"
            "---\n\n"
            "## 当前工作\nancient\n"
        )
        Path(hot_path).write_text(old_content, encoding="utf-8")
        state = read_hot(config)
        assert state is not None
        assert state["expired"] is True
        assert state["summary"] == "ancient"


# ── Edge cases ──


class TestEdgeCases:
    def test_malformed_file(self, tmp_hot: Any) -> None:
        hot_path, config = tmp_hot
        Path(hot_path).write_text("not-yaml-like\njust text", encoding="utf-8")
        state = read_hot(config)
        assert state is not None
        assert state["expired"] is False

    def test_empty_front_matter(self, tmp_hot: Any) -> None:
        hot_path, config = tmp_hot
        Path(hot_path).write_text("---\n---", encoding="utf-8")
        state = read_hot(config)
        assert state is not None
        assert state["expired"] is False
