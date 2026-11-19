from __future__ import annotations

import json
from pathlib import Path

from nonebot_plugin_feature_switch.store import (
    FEATURE_DEFAULTS,
    STATE_VERSION,
    FeatureSwitchStore,
    default_state,
    state_path_from_env,
)
from nonebot_plugin_feature_switch.store import (
    test_groups_from_env as read_test_groups,
)


def _write(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_default_state_is_safe(monkeypatch) -> None:
    monkeypatch.delenv("FEATURE_SWITCH_TEST_GROUPS", raising=False)
    state = default_state()

    assert state["version"] == STATE_VERSION
    assert state["group_default"] is False
    assert state["group_defaults"] == {}
    assert state["feature_defaults"]["music_score_reactor"] is False
    assert state["feature_defaults"]["ws_maimai"] is True
    assert state["matrix"] == {}
    assert read_test_groups() == set()


def test_default_state_reads_test_groups(monkeypatch) -> None:
    monkeypatch.setenv("FEATURE_SWITCH_TEST_GROUPS", "100001, 100002")
    state = default_state()
    assert state["group_defaults"] == {"100001": True, "100002": True}


def test_state_path_default_and_override(monkeypatch) -> None:
    monkeypatch.delenv("FEATURE_SWITCH_STATE_PATH", raising=False)
    assert state_path_from_env() == Path("data") / "feature_switch" / "state.json"
    monkeypatch.setenv("FEATURE_SWITCH_STATE_PATH", "/tmp/custom-state.json")
    assert state_path_from_env() == Path("/tmp/custom-state.json")


def test_four_layer_fallback(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "state.json",
        {
            "version": 2,
            "group_default": True,
            "group_defaults": {"100001": False},
            "feature_defaults": {"imitate": True, "music_score_reactor": False},
            "matrix": {"imitate": {"100001": False}},
        },
    )
    store = FeatureSwitchStore(path)

    # matrix > feature_defaults
    assert store.is_enabled("imitate", 100001) is False
    # feature_defaults > group_default
    assert store.is_enabled("imitate", 100002) is True
    assert store.is_enabled("music_score_reactor", 100002) is False
    # group_defaults > group_default
    assert store.is_enabled("quote_card", 100001) is False
    assert store.is_enabled("quote_card", 100002) is True
    # 私聊永远放行
    assert store.is_enabled("quote_card", None) is True

    assert store.source_of("imitate", 100001) == "矩阵显式"
    assert store.source_of("imitate", 100002) == "功能默认"
    assert store.source_of("quote_card", 100002) == "群默认"


async def test_atomic_write_and_audit(tmp_path: Path) -> None:
    path = tmp_path / "data" / "state.json"
    store = FeatureSwitchStore(path)
    changes = await store.set_many(["quote_card"], ["100001"], True, "tester")

    assert changes == [("quote_card", "100001", False, True)]
    payload = json.loads(path.read_text("utf-8"))
    assert payload["version"] == 2
    assert payload["updated_at"]
    assert payload["matrix"]["quote_card"]["100001"] is True
    assert not list(path.parent.glob("*.tmp*"))

    audit = tmp_path / "data" / "audit.jsonl"
    records = [json.loads(line) for line in audit.read_text("utf-8").splitlines() if line.strip()]
    assert records
    assert records[-1]["actor"] == "tester"
    assert records[-1]["action"] == "开"
    assert "ts" in records[-1] and "changes" in records[-1]


async def test_bad_file_keeps_last_good_then_heals(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    store = FeatureSwitchStore(path)
    await store.set_many(["quote_card"], ["100001"], True, "tester")
    assert store.is_enabled("quote_card", 100001) is True

    path.write_text("{ broken json", encoding="utf-8")
    assert store.is_enabled("quote_card", 100001) is True
    assert store.parse_error_count >= 1

    await store.set_many(["quote_card"], ["100001"], False, "tester")
    payload = json.loads(path.read_text("utf-8"))
    assert payload["version"] == 2
    assert store.is_enabled("quote_card", 100001) is False


async def test_mtime_hot_reload(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "state.json",
        {
            "version": 2,
            "group_default": False,
            "group_defaults": {},
            "feature_defaults": dict(FEATURE_DEFAULTS),
            "matrix": {},
        },
    )
    store = FeatureSwitchStore(path)
    assert store.is_enabled("quote_card", 100009) is False

    import os
    import time

    external = json.loads(path.read_text("utf-8"))
    external["matrix"]["quote_card"] = {"100009": True}
    _write(path, external)
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    time.sleep(0.001)

    assert store.is_enabled("quote_card", 100009) is True
    assert store.reload_count >= 1


async def test_legacy_state_migration(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "old-state.json",
        {
            "version": 2,
            "updated_at": None,
            "group_default": False,
            "group_defaults": {"100001": True},
            "feature_defaults": {"music_score_reactor": False},
            "matrix": {},
        },
    )
    store = FeatureSwitchStore(path)

    assert store.feature_defaults()["ws_maimai"] is True
    assert store.is_enabled("ws_maimai", 100002) is True
    assert "ws_maimai" not in path.read_text("utf-8")

    await store.set_many(["ws_maimai"], ["100002"], False, "tester")
    payload = json.loads(path.read_text("utf-8"))
    assert payload["feature_defaults"]["ws_maimai"] is True
    assert payload["feature_defaults"]["music_score_reactor"] is False
    assert payload["matrix"]["ws_maimai"]["100002"] is False


async def test_set_global_and_reset(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FEATURE_SWITCH_TEST_GROUPS", "100001")
    path = tmp_path / "state.json"
    store = FeatureSwitchStore(path)

    changes = await store.set_global(["quote_card"], True, "tester")
    assert changes
    assert store.is_enabled("quote_card", 100001) is True
    assert store.is_enabled("quote_card", 100002) is True
    assert store.feature_defaults()["quote_card"] is True

    before, after = await store.reset("quote_card", "100001", "tester")
    assert before is True
    assert after is True
    assert "100001" not in store.groups_of("quote_card")


def test_corrupt_root_is_last_good(tmp_path: Path) -> None:
    path = _write(tmp_path / "state.json", {"version": 2, "matrix": {"quote_card": {"100001": True}}})
    store = FeatureSwitchStore(path)
    assert store.is_enabled("quote_card", 100001) is True

    path.write_text("[]", encoding="utf-8")
    assert store.is_enabled("quote_card", 100001) is True
    assert store.parse_error_count == 1
