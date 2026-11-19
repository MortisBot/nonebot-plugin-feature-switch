"""测试环境：真实 NoneBot 初始化（无 network driver），用于 matcher/rule 门禁。"""

from __future__ import annotations

import nonebot

nonebot.init(driver="~none", command_start={"/"}, log_level="ERROR")
