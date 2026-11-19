"""私聊管理命令（仅超管）。

命令入口：
- ``/开关``（别名 ``/功能``）——完整矩阵管理；
- 私聊直接发 ``help`` / ``/help`` / ``帮助`` / ``?`` —— 查看插件（功能）列表与管理命令一览；
- 仅私聊、仅 ``SUPERUSER`` 生效：非超管静默；群聊里静默忽略（不暴露管理命令存在）；
- 危险操作（含"全部"或目标群数 > 3）需 60s 内二次确认 ``/开关 确认 <token>``；
- ``/开关 群 <群号> 开|关`` 一键启停某群所有功能（``ping`` 常开不参与），
  简写 ``/开关 群开 <群号>`` / ``/开关 群关 <群号>``。
"""

from __future__ import annotations

import re
import secrets
import time

from nonebot.adapters.onebot.v11 import PrivateMessageEvent
from nonebot.exception import FinishedException
from nonebot.log import logger
from nonebot.permission import SUPERUSER
from nonebot.plugin.on import on_message
from nonebot.rule import Rule

from .gate import FEATURES, GATED_FEATURE_KEYS
from .store import FeatureSwitchStore

ADMIN_RE = re.compile(r"^[/]?(?:开关|功能)(?:\s+(.*))?$", re.S)
HELP_RE = re.compile(r"^[/]?(?:help|帮助|\?|？)$", re.I)
CONFIRM_TTL = 60.0
DANGER_GROUP_COUNT = 3
MAX_REPLY_CHARS = 1500

_pending: dict[str, tuple[float, str, list[str], list[str], bool]] = {}


def _feature_label(key: str) -> str:
    spec = FEATURES.get(key)
    return f"{key}（{spec['label']}）" if spec else key


def _fmt_enabled(value: bool) -> str:
    return "✅开" if value else "❌关"


def _truncate(text: str, limit: int = MAX_REPLY_CHARS) -> str:
    return text if len(text) <= limit else text[: limit - 20] + "…（已截断）"


def _help_text(store: FeatureSwitchStore | None = None) -> str:
    """插件（功能）列表 + 管理命令一览；供 help / /开关 使用。"""
    feature_defaults = store.feature_defaults() if store is not None else {}
    group_defaults = store.group_defaults() if store is not None else {}

    lines = ["功能总开关 · 超管私聊帮助", "", "【插件/功能列表】（按 功能×群 独立开关）"]
    for key, spec in FEATURES.items():
        if spec.get("always_on"):
            lines.append(f"· {key}：{spec['label']}，不纳入矩阵")
        else:
            default = feature_defaults.get(key)
            default_text = "随群默认" if default is None else _fmt_enabled(default)
            lines.append(f"· {key}：{spec['label']}，默认={default_text}")
    if group_defaults:
        special = group_defaults.get("groups") or {}
        lines.append(
            f"群默认：特殊群={special or '无'}；其它群={_fmt_enabled(bool(group_defaults.get('default')))}"
        )
    lines.append("外部 WS 消费者（ws_*）由外部 WS 中继读取本矩阵按群过滤，默认全转发")
    lines.extend(
        [
            "",
            "【管理命令】（仅私聊；危险操作需二次确认）",
            "/开关 列表                     功能列表与显式开关",
            "/开关 矩阵 [功能]              查看 功能×群 矩阵",
            "/开关 查群 <群号>              某群各功能状态",
            "/开关 查 <功能>                某功能开放/关闭的群",
            "/开关 群 <群号> 开|关          一键开启/关闭该群所有功能（ping 除外）",
            "/开关 群开 <群号> / 群关 <群号>  同上（简写，不带开/关则查看状态）",
            "/开关 开|关 <功能|全部> <群号|全部>[,...]",
            "/开关 批量 <开|关> <功能列表> <群号列表>",
            "/开关 默认 <功能> <开|关>      修改功能级默认",
            "/开关 复位 <功能> <群号>       清除显式覆盖，回落默认",
            "/开关 确认 <token> / 取消      危险操作二次确认（60s）",
            "示例：/开关 群 <群号> 关    /开关 开 chart_download <群号>",
        ]
    )
    return "\n".join(lines)


def _is_admin_text(event) -> bool:
    if not isinstance(event, PrivateMessageEvent):
        return False
    try:
        text = event.get_plaintext().strip()
        return bool(ADMIN_RE.match(text) or HELP_RE.match(text))
    except Exception:
        return False


def _validate_features(args: list[str]) -> list[str] | None:
    if len(args) != 1:
        return None
    raw = args[0]
    if raw == "全部":
        return list(GATED_FEATURE_KEYS)
    keys = [item.strip() for item in raw.split(",") if item.strip()]
    if keys and all(key in FEATURES and not FEATURES[key].get("always_on") for key in keys):
        return keys
    return None


def _validate_groups(args: list[str]) -> list[str] | None:
    if len(args) != 1:
        return None
    if args[0] == "全部":
        return ["全部"]
    groups = [item.strip() for item in args[0].split(",") if item.strip()]
    if groups and all(group.isdigit() for group in groups):
        return groups
    return None


def setup_admin(store: FeatureSwitchStore):
    """注册私聊管理 matcher；返回 matcher 类便于测试。"""
    matcher = on_message(rule=Rule(_is_admin_text), permission=SUPERUSER, priority=0, block=True)

    async def _reply(text: str) -> None:
        await matcher.finish(_truncate(text))

    async def _apply(features: list[str], groups: list[str], enabled: bool, actor: str) -> str:
        if groups == ["全部"]:
            changes = await store.set_global(features, enabled, actor)
        else:
            changes = await store.set_many(features, groups, enabled, actor)
        lines = [f"{'开启' if enabled else '关闭'} {len(changes)} 项："]
        for feature, group_id, before, after in changes[:15]:
            lines.append(f"· {feature} @ {group_id}: {_fmt_enabled(before)} → {_fmt_enabled(after)}")
        if len(changes) > 15:
            lines.append(f"… 共 {len(changes)} 项")
        return "\n".join(lines)

    async def _apply_group_all(group_id: str, enabled: bool, actor: str) -> str:
        """一键启停某群的全部可开关功能（ping 常开，不在其中）。"""
        features = list(GATED_FEATURE_KEYS)
        changes = await store.set_many(features, [group_id], enabled, actor)
        lines = [f"{'已开启' if enabled else '已关闭'}群 {group_id} 的全部 {len(changes)} 项功能："]
        for feature, _gid, before, after in changes:
            lines.append(f"· {feature}: {_fmt_enabled(before)} → {_fmt_enabled(after)}")
        if enabled:
            lines.append(
                f"提示：music_score_reactor 与 ws_*（外部 WS 中继）也在其中；"
                f"如不需要可单独关，例如 /开关 关 music_score_reactor {group_id}"
            )
        return "\n".join(lines)

    async def _group_status(group_id: str) -> str:
        lines = [f"群 {group_id} 的功能状态："]
        for key, spec in FEATURES.items():
            if spec.get("always_on"):
                lines.append(f"· {key}: ✅开（常开）")
            else:
                lines.append(
                    f"· {key}: {_fmt_enabled(store.is_enabled(key, group_id))}"
                    f"（来源：{store.source_of(key, group_id)}）"
                )
        return "\n".join(lines)

    @matcher.handle()
    async def _handle(event: PrivateMessageEvent):
        raw = event.get_plaintext().strip()
        if HELP_RE.match(raw):
            await _reply(_help_text(store))
            return
        matched = ADMIN_RE.match(raw)
        body = (matched.group(1) or "").strip() if matched else ""
        parts = body.split()
        cmd = parts[0] if parts else ""
        args = parts[1:]
        actor = event.get_user_id()
        try:
            await _dispatch(cmd, args, actor)
        except FinishedException:  # finish()/reject() 等正常控制流，必须原样抛出
            raise
        except Exception as exc:  # 管理命令出错不崩 bot，回复可读错误
            logger.opt(exception=exc).error("feature_switch: admin command failed")
            await _reply(f"操作失败：{type(exc).__name__}: {exc}")

    async def _dispatch(cmd: str, args: list[str], actor: str) -> None:
        if not cmd or cmd in {"帮助", "help", "?", "？"}:
            await _reply(_help_text(store))
            return

        if cmd in {"列表", "功能列表"}:
            lines = [
                "功能列表（默认策略：FEATURE_SWITCH_TEST_GROUPS 中的群开 / 其它群关；"
                "music_score_reactor 功能级默认关；ws_* 默认开=全转发）"
            ]
            defaults = store.feature_defaults()
            for key, spec in FEATURES.items():
                if spec.get("always_on"):
                    lines.append(f"· {key}（{spec['label']}）常开，不纳入矩阵")
                    continue
                default = _fmt_enabled(defaults[key]) if key in defaults else "随群默认"
                groups = store.groups_of(key)
                on_groups = [g for g, v in groups.items() if v]
                off_groups = [g for g, v in groups.items() if not v]
                lines.append(
                    f"· {key}（{spec['label']}）默认={default} 显式开={on_groups} 显式关={off_groups}"
                )
            await _reply("\n".join(lines))
            return

        if cmd in {"矩阵", "matrix"}:
            feature = args[0] if args else None
            if feature and feature not in FEATURES:
                await _reply(f"未知功能 key: {feature}；可用：{', '.join(FEATURES)}")
                return
            group_defaults = store.group_defaults()
            lines = [
                "功能×群 矩阵（显式值优先）",
                f"群默认：默认={_fmt_enabled(group_defaults['default'])} 特殊群={group_defaults['groups']}",
            ]
            for key, spec in FEATURES.items():
                if feature and key != feature:
                    continue
                if spec.get("always_on"):
                    lines.append(f"{key}: 常开（不纳管）")
                else:
                    lines.append(f"{key}: 显式={store.groups_of(key) or '无'}")
            await _reply("\n".join(lines))
            return

        if cmd == "查群":
            groups = _validate_groups(args)
            if not groups or groups == ["全部"]:
                await _reply("用法：/开关 查群 <群号>")
                return
            await _reply(await _group_status(groups[0]))
            return

        if cmd in {"查", "功能"}:
            features = _validate_features(args)
            if not features or len(features) != 1:
                await _reply("用法：/开关 查 <功能>")
                return
            key = features[0]
            groups = store.groups_of(key)
            on_groups = [g for g, v in groups.items() if v]
            off_groups = [g for g, v in groups.items() if not v]
            await _reply(f"{key}：显式开启群={on_groups or '无'}；显式关闭群={off_groups or '无'}")
            return

        if cmd == "群":
            if not args or not args[0].isdigit():
                await _reply("用法：/开关 群 <群号> 开|关（只带群号 = 查看该群状态）")
                return
            group_id = args[0]
            if len(args) == 1:
                await _reply(await _group_status(group_id))
                return
            if args[1] not in {"开", "关"}:
                await _reply(f"用法：/开关 群 {group_id} 开|关")
                return
            await _reply(await _apply_group_all(group_id, args[1] == "开", actor))
            return

        if cmd in {"群开", "群关"}:
            if len(args) != 1 or not args[0].isdigit():
                await _reply(f"用法：/开关 {cmd} <群号>")
                return
            await _reply(await _apply_group_all(args[0], cmd == "群开", actor))
            return

        if cmd in {"开", "关"}:
            enabled = cmd == "开"
            features = _validate_features(args[:1])
            groups = _validate_groups(args[1:2])
            if not features or not groups:
                await _reply(f"用法：/开关 {'开' if enabled else '关'} <功能|全部> <群号|全部>[,...]")
                return
            danger = "全部" in groups or len(groups) > DANGER_GROUP_COUNT
            summary = f"{'开启' if enabled else '关闭'} 功能={features} 群={groups}" + ("（全局）" if groups == ["全部"] else "")
            if danger:
                token = secrets.token_hex(3)
                _pending[token] = (time.monotonic() + CONFIRM_TTL, summary, features, groups, enabled)
                await _reply(
                    f"⚠️ 危险操作待确认（60s）：{summary}\n"
                    f"回复 /开关 确认 {token} 执行，/开关 取消 放弃"
                )
                return
            await _reply(await _apply(features, groups, enabled, actor))
            return

        if cmd == "批量":
            if len(args) < 3 or args[0] not in {"开", "关"}:
                await _reply("用法：/开关 批量 <开|关> <功能列表> <群号列表>")
                return
            enabled = args[0] == "开"
            features = _validate_features([args[1]])
            groups = _validate_groups([args[2]])
            if not features or not groups:
                await _reply("批量参数非法：功能或群号列表无法解析")
                return
            await _reply(await _apply(features, groups, enabled, actor))
            return

        if cmd == "默认":
            features = _validate_features(args[:1])
            if not features or len(features) != 1 or len(args) < 2 or args[1] not in {"开", "关"}:
                await _reply("用法：/开关 默认 <功能> <开|关>")
                return
            before = await store.set_feature_default(features[0], args[1] == "开", actor)
            await _reply(f"{features[0]} 功能级默认：{before} → {args[1] == '开'}")
            return

        if cmd == "复位":
            features = _validate_features(args[:1])
            groups = _validate_groups(args[1:2])
            if not features or len(features) != 1 or not groups or groups == ["全部"]:
                await _reply("用法：/开关 复位 <功能> <群号>")
                return
            before, after = await store.reset(features[0], groups[0], actor)
            await _reply(f"已复位 {features[0]} @ {groups[0]}：{before} → {after}（回落默认）")
            return

        if cmd == "确认":
            if len(args) != 1:
                await _reply("用法：/开关 确认 <token>")
                return
            item = _pending.pop(args[0], None)
            if not item or item[0] < time.monotonic():
                await _reply("确认码无效或已过期")
                return
            _, summary, features, groups, enabled = item
            await _reply(await _apply(features, groups, enabled, actor))
            return

        if cmd == "取消":
            _pending.clear()
            await _reply("已取消所有待确认操作")
            return

        await _reply("未知子命令，发送 /开关 查看帮助")

    logger.info("feature_switch: admin commands registered (private-only, SUPERUSER)")
    return matcher
