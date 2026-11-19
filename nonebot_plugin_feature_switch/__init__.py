"""功能总开关 v2 —— 按「功能 × 群」控制各功能在哪些群开放。

设计要点：
- 管理仅限超管（``SUPERUSERS``）**私聊**；群聊里发管理命令静默忽略。
- 群聊生效：功能在某群关闭时不响应、不主动行为；私聊不受影响。
- ``FEATURE_SWITCH_TEST_GROUPS`` 中的群默认全开（默认空）、其它群默认关闭；
  ``music_score_reactor`` 功能级默认关。
- ``ping`` 常开（不包装 matcher，仅作为连通性诊断）。
- 状态：``FEATURE_SWITCH_STATE_PATH``，默认 ``data/feature_switch/state.json``。

实现机制：本插件在 ``driver.on_startup``（以及 ``on_bot_connect`` 兜底）遍历
``nonebot.message.matchers``，按 matcher 的模块名映射到功能 key，把 ``matcher.rule``
替换为「先查 (功能, 群) 矩阵、关闭则短路返回 False，否则委托原 Rule」的包装 Rule。

兼容/降级：``FEATURE_SWITCH_MODE=wrap``（默认，推荐）或 ``append``（保守，原 rule
仍会被并发执行，仅作为 NoneBot 内部 API 变化时的降级路径）。
"""

from __future__ import annotations

import os

from nonebot import get_driver, logger
from nonebot.adapters import Bot
from nonebot.plugin import PluginMetadata

from .admin import setup_admin
from .gate import FEATURES, format_install_summary, install
from .store import FeatureSwitchStore, default_state

__plugin_meta__ = PluginMetadata(
    name="功能总开关",
    description="按「功能 × 群」启用/关闭已安装插件的 matcher 门禁，状态文件可热更新。",
    usage=(
        "群聊自动生效。超管私聊发送 help 或 /开关 查看功能列表与管理命令；"
        "危险操作需要二次确认。"
    ),
    type="application",
    homepage="https://github.com/MortisBot/nonebot-plugin-feature-switch",
    supported_adapters={"~onebot.v11"},
)

_PLUGIN_VERSION = 2

_ACTIVE = os.getenv("FEATURE_SWITCH_ACTIVE", "true").strip().lower() not in {"0", "false", "no", "off"}
_MODE = os.getenv("FEATURE_SWITCH_MODE", "wrap").strip().lower()
if _MODE not in {"wrap", "append"}:
    logger.warning(f"feature_switch: unknown FEATURE_SWITCH_MODE={_MODE!r}, fallback to 'wrap'")
    _MODE = "wrap"

STORE = FeatureSwitchStore()
driver = get_driver()

_installed: dict[str, list] | None = None


def get_mode() -> str:
    return _MODE


def install_gate() -> dict[str, list]:
    """安装/刷新门禁（幂等）。返回 {feature: [matcher...]}。"""
    global _installed
    try:
        _installed = install(STORE, mode=_MODE)
    except Exception as exc:  # 绝不因门禁安装失败拖垮 bot 启动
        logger.opt(exception=exc).error("feature_switch: install gate failed")
        _installed = {}
        return _installed
    logger.info(format_install_summary(_installed, mode=_MODE, state_path=str(STORE.path)))
    return _installed


async def _rescan(_bot: Bot) -> None:
    """bot 连接时兜底重扫，覆盖启动阶段之后才注册的 matcher；幂等。"""
    install_gate()


if _ACTIVE:
    driver.on_startup(install_gate)
    driver.on_bot_connect(_rescan)
    setup_admin(STORE)
    logger.info(
        f"feature_switch: v{_PLUGIN_VERSION} active=True mode={_MODE} state={STORE.path} "
        f"features={sorted(FEATURES)}"
    )
else:
    logger.warning("feature_switch: FEATURE_SWITCH_ACTIVE=false, gates & admin commands disabled")


__all__ = ["STORE", "FEATURES", "install_gate", "get_mode", "default_state"]
