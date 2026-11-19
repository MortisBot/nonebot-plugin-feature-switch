"""matcher 级按功能门禁。

核心：
1. ``FEATURES``：功能 key → 展示名 + matcher 模块名匹配词（按 "." 切分后的段匹配，
   兼容 ``plugins.chart_download`` / ``src.plugins.chart_download`` /
   ``nonebot_plugin_chart_downloader`` 等布局）；可用 env
   ``FEATURE_SWITCH_MODULE_MAP``（JSON：``{"功能key": ["额外模块词", ...]}``）补充。
2. ``resolve_feature(matcher)`` / ``resolve_module_feature(module_name)``：映射功能。
3. ``FeatureGatedRule``：包装原 Rule，群聊先查矩阵、关闭则短路；私聊放行。
4. ``install(store, mode)``：遍历 ``nonebot.matcher.matchers``，幂等包装。
   - ``mode="wrap"``（默认）：替换 rule 为 ``FeatureGatedRule``，关闭时原规则不执行；
   - ``mode="append"``（降级）：``rule = rule & Rule(checker)``，原规则仍会被并发执行，
     仅作为 NoneBot 内部 API 变化时的保守回退。
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any

from nonebot.adapters import Bot, Event
from nonebot.log import logger
from nonebot.matcher import Matcher, matchers
from nonebot.rule import Rule
from nonebot.typing import T_State

if TYPE_CHECKING:
    from .store import FeatureSwitchStore

# 功能 key -> 展示名 + 模块名匹配词；always_on=True 的不会被包装（常开）
FEATURES: dict[str, dict[str, Any]] = {
    "quote_card": {
        "label": "引用消息卡片",
        "match": ["quote_card", "nonebot_plugin_quote_card"],
        "always_on": False,
    },
    "mface_pool": {
        "label": "表情池（收集/概率发送）",
        "match": ["mface_pool", "nonebot_plugin_mface_pool"],
        "always_on": False,
    },
    "group_rank": {
        "label": "群排行（精华榜/发言榜）",
        "match": ["group_rank", "nonebot_plugin_group_rank"],
        "always_on": False,
    },
    "imitate": {
        "label": "模仿",
        "match": ["imitate", "nonebot_plugin_imitate"],
        "always_on": False,
    },
    "chart_download": {
        "label": "谱面下载/索引/别名",
        "match": [
            "chart_download",
            "chart_index",
            "chart_alias",
            "nonebot_plugin_chart_downloader",
        ],
        "always_on": False,
    },
    "music_score_reactor": {
        "label": "成绩图贴表情",
        "match": ["music_score_reactor", "nonebot_plugin_music_score_reactor"],
        "always_on": False,
    },
    # 外部 WS 消费者（NapCat 并行外连的 maimai/pjsk/misc）：本插件没有对应 matcher，
    # 由外部 WS 中继读取同一份 state.json 按群过滤；这里纳入同一矩阵供管理命令使用。
    "ws_maimai": {"label": "外部 WS 消费者：maimai（按群过滤）", "match": [], "external": True, "always_on": False},
    "ws_pjsk": {"label": "外部 WS 消费者：pjsk（按群过滤）", "match": [], "external": True, "always_on": False},
    "ws_misc": {"label": "外部 WS 消费者：misc（按群过滤）", "match": [], "external": True, "always_on": False},
    # ping 只读连通性诊断、无内容/主动行为，保持常开（不纳入矩阵）
    "ping": {"label": "连通性诊断（常开）", "match": ["ping"], "always_on": True},
}

# 纳入管理/参数校验的功能 key（含 external；external 无 matcher，install 会跳过包装）
GATED_FEATURE_KEYS: list[str] = [k for k, v in FEATURES.items() if not v.get("always_on")]


def _load_env_module_map() -> dict[str, list[str]]:
    raw = os.getenv("FEATURE_SWITCH_MODULE_MAP", "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except ValueError as exc:
        logger.warning(f"feature_switch: invalid FEATURE_SWITCH_MODULE_MAP: {exc!r}")
        return {}
    out: dict[str, list[str]] = {}
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, str):
                value = [value]
            if isinstance(value, list):
                out[str(key)] = [str(v) for v in value if str(v)]
    return out


def _merge_extra_patterns(features: dict[str, dict[str, Any]]) -> None:
    for key, patterns in _load_env_module_map().items():
        if key in features:
            merged = list(features[key]["match"])
            for pattern in patterns:
                if pattern not in merged:
                    merged.append(pattern)
            features[key]["match"] = merged


_merge_extra_patterns(FEATURES)


def _tokens(*names: str | None) -> set[str]:
    tokens: set[str] = set()
    for name in names:
        if name:
            tokens.update(part for part in name.split(".") if part)
    return tokens


def _match_tokens(tokens: set[str], pattern: str) -> bool:
    return any(
        token == pattern or token.endswith("_" + pattern) or token.startswith(pattern + "_")
        for token in tokens
    )


def resolve_module_feature(module_name: str | None, plugin_name: str | None = None, plugin_id: str | None = None) -> str | None:
    """按模块名/插件名（"点分段"）解析功能 key；无法识别返回 None。"""
    tokens = _tokens(module_name, plugin_name, plugin_id)
    if not tokens:
        return None
    for feature, spec in FEATURES.items():
        for pattern in spec["match"]:
            if _match_tokens(tokens, pattern):
                return feature
    return None


def resolve_feature(matcher: type[Matcher]) -> str | None:
    return resolve_module_feature(matcher.module_name, matcher.plugin_name, matcher.plugin_id)


class FeatureGatedRule(Rule):
    """原 Rule 的包装：群聊先查 (功能, 群) 矩阵，关闭则短路返回 False；私聊永远放行。"""

    __slots__ = ("base", "feature", "store")

    def __init__(self, base: Rule, feature: str, store: FeatureSwitchStore) -> None:
        super().__init__()  # checkers 留空，由本类 __call__ 接管
        self.base = base
        self.feature = feature
        self.store = store

    async def __call__(  # type: ignore[override]
        self,
        bot: Bot,
        event: Event,
        state: T_State,
        stack=None,
        dependency_cache=None,
    ) -> bool:
        group_id = getattr(event, "group_id", None)
        if group_id is not None and not self.store.is_enabled(self.feature, group_id):
            logger.trace(f"feature_switch: feature={self.feature} disabled in group={group_id}")
            return False
        return await self.base(bot=bot, event=event, state=state, stack=stack, dependency_cache=dependency_cache)


def _append_checker(store: FeatureSwitchStore, feature: str):
    async def _checker(event: Event) -> bool:
        group_id = getattr(event, "group_id", None)
        if group_id is None:
            return True
        return store.is_enabled(feature, group_id)

    return _checker


def install(store: FeatureSwitchStore, mode: str | None = None) -> dict[str, list[type[Matcher]]]:
    """扫描并包装 matcher（幂等）。

    返回 ``{feature: [被包装的 Matcher 类, ...]}``；``mode`` 缺省读 env
    ``FEATURE_SWITCH_MODE``（wrap/append，非法值回退 wrap）。
    """
    selected_mode = (mode or os.getenv("FEATURE_SWITCH_MODE", "wrap")).strip().lower()
    if selected_mode not in {"wrap", "append"}:
        logger.warning(f"feature_switch: unknown mode={selected_mode!r}, fallback to 'wrap'")
        selected_mode = "wrap"

    installed: dict[str, list[type[Matcher]]] = {}
    for _priority, matcher_list in sorted(matchers.items()):
        for MatcherCls in matcher_list:
            feature = getattr(MatcherCls, "_fs_feature", None) or resolve_feature(MatcherCls)
            if feature is None:
                continue
            if FEATURES.get(feature, {}).get("always_on"):
                continue  # 常开功能不包装
            if FEATURES.get(feature, {}).get("external"):
                continue  # 外部 WS 消费者由中继按同一 state 过滤，NoneBot 侧不包装
            if getattr(MatcherCls, "_fs_installed", False):
                installed.setdefault(feature, []).append(MatcherCls)
                continue
            if selected_mode == "append":
                MatcherCls.rule = MatcherCls.rule & Rule(_append_checker(store, feature))  # type: ignore[assignment]
            else:
                MatcherCls._fs_base_rule = MatcherCls.rule  # type: ignore[attr-defined]
                MatcherCls.rule = FeatureGatedRule(MatcherCls.rule, feature, store)  # type: ignore[assignment]
            MatcherCls._fs_feature = feature  # type: ignore[attr-defined]
            MatcherCls._fs_installed = True  # type: ignore[attr-defined]
            MatcherCls._fs_mode = selected_mode  # type: ignore[attr-defined]
            installed.setdefault(feature, []).append(MatcherCls)
    return installed


def format_install_summary(installed: dict[str, list[type[Matcher]]], *, mode: str, state_path: str) -> str:
    total = sum(len(v) for v in installed.values())
    detail = ", ".join(f"{key}={len(value)}" for key, value in sorted(installed.items())) or "none"
    return (
        f"feature_switch: gated matchers={total} mode={mode} features=[{detail}] "
        f"state={state_path}"
    )
