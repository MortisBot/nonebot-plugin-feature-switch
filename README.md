# nonebot-plugin-feature-switch

_✨ 按「功能 × 群」控制已安装插件是否响应，超管私聊管理。 ✨_

<a href="./LICENSE"><img src="https://img.shields.io/github/license/MortisBot/nonebot-plugin-feature-switch.svg" alt="license"></a>
<a href="https://pypi.python.org/pypi/nonebot-plugin-feature-switch"><img src="https://img.shields.io/pypi/v/nonebot-plugin-feature-switch.svg" alt="pypi"></a>
<img src="https://img.shields.io/badge/python-3.10+-blue.svg" alt="python">

## 安装

在 NoneBot2 项目根目录下执行：

```bash
nb plugin install nonebot-plugin-feature-switch
```

或手动安装：

```bash
pip install nonebot-plugin-feature-switch
```

并在 `pyproject.toml` 的 `[tool.nonebot]` 中追加：

```toml
plugins = ["nonebot_plugin_feature_switch"]
```

## 配置

在 `.env` 中配置（环境变量名即配置项大写）：

| 配置项 | 必填 | 默认值 | 说明 |
|:---:|:---:|:---:|:---|
| `FEATURE_SWITCH_ACTIVE` | 否 | `true` | 是否安装门禁 |
| `FEATURE_SWITCH_MODE` | 否 | `wrap` | `wrap`（推荐）/ `append` |
| `FEATURE_SWITCH_STATE_PATH` | 否 | `data/feature_switch/state.json` | 状态文件 |
| `FEATURE_SWITCH_TEST_GROUPS` | 否 | 空 | 默认放行的群 |
| `SUPERUSERS` | 是 | 空 | 超管 QQ，管理命令唯一权限来源 |

## 使用

超管私聊使用（群聊/非超管静默）：

| 命令 | 说明 |
|:---:|:---|
| `/开关` | 帮助 |
| `/开关 列表` | 功能列表与默认值 |
| `/开关 矩阵 [功能]` | 功能 × 群矩阵 |
| `/开关 群 <群号> 开\|关` | 一键启停该群所有功能 |
| `/开关 开\|关 <功能\|全部> <群号\|全部>` | 精细控制 |
| `/开关 默认 <功能> 开\|关` | 修改功能级默认 |
| `/开关 复位 <功能> <群号>` | 清除显式覆盖 |

需要 `nonebot2>=2.5,<2.6`（依赖 matcher 内部 API）。

## 适配器

OneBot v11（`supported_adapters={"~onebot.v11"}`）。

## License

[MIT](./LICENSE)

> 维护模式：原项目已停止运营，本插件按 best-effort 维护，无 SLA。
