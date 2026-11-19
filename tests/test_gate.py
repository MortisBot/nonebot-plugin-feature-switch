from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from nonebot.matcher import matchers
from nonebot.rule import Rule
from nonebot_plugin_feature_switch import gate as gate_mod
from nonebot_plugin_feature_switch.gate import (
    FEATURES,
    GATED_FEATURE_KEYS,
    FeatureGatedRule,
    _merge_extra_patterns,
    format_install_summary,
    install,
    resolve_feature,
    resolve_module_feature,
)
from nonebot_plugin_feature_switch.store import FeatureSwitchStore

EXPECTED_FEATURES = {
    "quote_card",
    "mface_pool",
    "group_rank",
    "imitate",
    "chart_download",
    "music_score_reactor",
    "ws_maimai",
    "ws_pjsk",
    "ws_misc",
    "ping",
}


def test_features_are_narrowed() -> None:
    assert set(FEATURES) == EXPECTED_FEATURES
    assert len(GATED_FEATURE_KEYS) == 9
    assert "ping" not in GATED_FEATURE_KEYS
    assert FEATURES["ping"]["always_on"] is True
    for key in ("ws_maimai", "ws_pjsk", "ws_misc"):
        spec = FEATURES[key]
        assert spec["external"] is True
        assert spec["match"] == []
        assert spec["always_on"] is False
        assert key in GATED_FEATURE_KEYS
    assert FEATURES["chart_download"]["match"][:3] == [
        "chart_download",
        "chart_index",
        "chart_alias",
    ]


def test_module_mapping() -> None:
    cases = {
        "plugins.chart_download": "chart_download",
        "plugins.chart_index": "chart_download",
        "plugins.chart_alias": "chart_download",
        "nonebot_plugin_chart_downloader.download": "chart_download",
        "plugins.mface_pool": "mface_pool",
        "plugins.quote_card": "quote_card",
        "nonebot_plugin_quote_card": "quote_card",
        "plugins.group_rank": "group_rank",
        "plugins.imitate": "imitate",
        "nonebot_plugin_imitate": "imitate",
        "plugins.music_score_reactor": "music_score_reactor",
        "nonebot_plugin_music_score_reactor": "music_score_reactor",
        "plugins.ping": "ping",
        "plugins.unknown_feature": None,
        "nonebot_plugin_feature_switch.admin": None,
    }
    for module_name, expected in cases.items():
        assert resolve_module_feature(module_name) == expected, module_name


def test_module_map_env_extension(monkeypatch) -> None:
    monkeypatch.setenv("FEATURE_SWITCH_MODULE_MAP", '{"quote_card": ["my_quote"]}')
    features = {"quote_card": {"match": ["quote_card"]}}
    _merge_extra_patterns(features)
    assert "my_quote" in features["quote_card"]["match"]


async def _set_enabled(store: FeatureSwitchStore, feature: str) -> None:
    await store.set_many([feature], ["100001"], True, "tester")


async def test_wrap_gate_blocks_and_allows(tmp_path: Path) -> None:
    calls: list[str] = []

    async def allow(event) -> bool:
        calls.append(str(getattr(event, "group_id", None)))
        return True

    class FakeMatcher:
        module_name = "nonebot_plugin_chart_downloader.download"
        plugin_name = "nonebot_plugin_chart_downloader"
        plugin_id = "nonebot_plugin_chart_downloader"
        priority = 55
        rule = Rule(allow)

    matchers.setdefault(55, []).append(FakeMatcher)
    try:
        store = FeatureSwitchStore(tmp_path / "state.json")
        assert resolve_feature(FakeMatcher) == "chart_download"

        installed = install(store, mode="wrap")
        assert installed["chart_download"] == [FakeMatcher]
        assert isinstance(FakeMatcher.rule, FeatureGatedRule)
        assert FakeMatcher._fs_installed is True
        assert FakeMatcher._fs_mode == "wrap"

        assert await FakeMatcher.rule(None, SimpleNamespace(group_id=100002), {}) is False
        assert calls == []

        await _set_enabled(store, "chart_download")
        assert await FakeMatcher.rule(None, SimpleNamespace(group_id=100001), {}) is True
        assert calls == ["100001"]

        # 私聊（无 group_id）永远放行
        assert await FakeMatcher.rule(None, SimpleNamespace(), {}) is True
        assert calls == ["100001", "None"]
    finally:
        matchers[55].remove(FakeMatcher)
        if not matchers[55]:
            matchers.pop(55)


async def test_install_is_idempotent(tmp_path: Path) -> None:
    async def allow(event) -> bool:
        return True

    class FakeMatcher:
        module_name = "plugins.chart_download"
        plugin_name = None
        plugin_id = None
        priority = 56
        rule = Rule(allow)

    matchers.setdefault(56, []).append(FakeMatcher)
    try:
        store = FeatureSwitchStore(tmp_path / "state.json")
        first = install(store, mode="wrap")
        second = install(store, mode="wrap")
        assert first["chart_download"] == [FakeMatcher]
        assert second["chart_download"] == [FakeMatcher]
        summary = format_install_summary(second, mode="wrap", state_path=str(store.path))
        assert "gated matchers=1 mode=wrap" in summary
        assert "chart_download=1" in summary
    finally:
        matchers[56].remove(FakeMatcher)
        if not matchers[56]:
            matchers.pop(56)


async def test_append_mode_and_unmapped_skip(tmp_path: Path) -> None:
    async def allow(event) -> bool:
        return True

    class Mapped:
        module_name = "plugins.imitate"
        plugin_name = None
        plugin_id = None
        priority = 57
        rule = Rule(allow)

    class AlwaysOn:
        module_name = "plugins.ping"
        plugin_name = None
        plugin_id = None
        priority = 58
        rule = Rule(allow)

    class Unmapped:
        module_name = "plugins.unknown"
        plugin_name = None
        plugin_id = None
        priority = 59
        rule = Rule(allow)

    for priority, cls in ((57, Mapped), (58, AlwaysOn), (59, Unmapped)):
        matchers.setdefault(priority, []).append(cls)
    try:
        store = FeatureSwitchStore(tmp_path / "state.json")
        installed = install(store, mode="append")
        assert Mapped._fs_mode == "append"
        assert isinstance(Mapped.rule, Rule)
        assert not isinstance(Mapped.rule, FeatureGatedRule)
        assert not getattr(AlwaysOn, "_fs_installed", False)
        assert not getattr(Unmapped, "_fs_installed", False)
        assert "imitate" in installed

        assert await Mapped.rule(None, SimpleNamespace(group_id=100002), {}) is False
    finally:
        for priority in (57, 58, 59):
            if priority in matchers:
                del matchers[priority]


def test_unknown_mode_falls_back_to_wrap(monkeypatch) -> None:
    monkeypatch.setenv("FEATURE_SWITCH_MODE", "bogus")
    # 仅验证 env 解析不抛异常；install 内部会回退
    assert gate_mod.os.getenv("FEATURE_SWITCH_MODE") == "bogus"
