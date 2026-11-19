<div align="center">
  <a href="https://v2.nonebot.dev/store">
    <img src="https://raw.githubusercontent.com/fllesser/nonebot-plugin-template/refs/heads/resource/.docs/NoneBotPlugin.svg" width="310" alt="NoneBotPlugin">
  </a>

# nonebot-plugin-feature-switch

_✨ 按「功能 × 群」控制已安装插件是否响应 ✨_

[![LICENSE](https://img.shields.io/github/license/MortisBot/nonebot-plugin-feature-switch.svg)](./LICENSE)
[![pypi](https://img.shields.io/pypi/v/nonebot-plugin-feature-switch.svg)](https://pypi.python.org/pypi/nonebot-plugin-feature-switch)
![python](https://img.shields.io/badge/python-3.10+-blue.svg)

</div>

## 📖 介绍

按「功能 × 群」给已安装插件加门禁：群内功能关闭时 matcher 规则短路，私聊放行；管理命令仅超管私聊可用，并且**不需要改业务插件代码**。

## 💿 安装

<details open>
<summary>使用 nb-cli 安装</summary>

在 NoneBot2 项目根目录下执行：

```bash
nb plugin install nonebot-plugin-feature-switch --upgrade
```

国内网络可换镜像源：

```bash
nb plugin install nonebot-plugin-feature-switch --upgrade -i "https://pypi.tuna.tsinghua.edu.cn/simple"
```

</details>

<details>
<summary>使用包管理器安装</summary>

在 NoneBot2 项目根目录下执行其一：

```bash
uv add nonebot-plugin-feature-switch
# 或
pdm add nonebot-plugin-feature-switch
# 或
poetry add nonebot-plugin-feature-switch
```

直接装仓库主分支（PyPI 包发布前可用）：

```bash
uv add git+https://github.com/MortisBot/nonebot-plugin-feature-switch@main
```

然后在 `pyproject.toml` 的 `[tool.nonebot]` 中追加：

```toml
plugins = ["nonebot_plugin_feature_switch"]
```

</details>

## ⚙️ 配置

在 NoneBot2 项目的 `.env` 中配置（配置项即环境变量名，大写）：

| 配置项 | 必填 | 默认值 | 说明 |
|:---:|:---:|:---:|:---|
| `SUPERUSERS` | 是 | 空 | 超管 QQ，管理命令唯一权限来源 |
| `FEATURE_SWITCH_ACTIVE` | 否 | `true` | 是否安装门禁（回滚用） |
| `FEATURE_SWITCH_MODE` | 否 | `wrap` | `wrap`（推荐）/ `append` |
| `FEATURE_SWITCH_STATE_PATH` | 否 | `data/feature_switch/state.json` | 状态文件 |
| `FEATURE_SWITCH_TEST_GROUPS` | 否 | 空 | 出厂默认放行的群 |

## 🎉 使用

仅超管私聊可用（群聊/非超管静默）：

| 命令 | 说明 |
|:---:|:---|
| `/开关` | 帮助 |
| `/开关 列表` | 功能列表与默认值 |
| `/开关 矩阵 [功能]` | 功能 × 群矩阵 |
| `/开关 群 <群号> 开\|关` | 一键启停该群所有功能 |
| `/开关 开\|关 <功能\|全部> <群号\|全部>` | 精细控制 |
| `/开关 默认 <功能> 开\|关` | 修改功能级默认 |
| `/开关 复位 <功能> <群号>` | 清除显式覆盖 |

## 🔌 适配器

OneBot v11（`supported_adapters={"~onebot.v11"}`）。门禁依赖 NoneBot 2.5 的 matcher 内部 API，`nonebot2` 锁定 `>=2.5,<2.6`；新插件需要补 `gate.py` 的 `FEATURES` 映射。

## 📄 License

[MIT](./LICENSE) · 维护模式（best-effort，无 SLA）
