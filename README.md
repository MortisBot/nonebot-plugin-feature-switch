# nonebot-plugin-feature-switch

按「功能 × 群」给已安装插件加门禁：群内功能关闭时 matcher 规则短路，私聊放行；管理命令仅超管私聊可用，并且**不需要改业务插件代码**。

## 第一次使用

1. 安装：

   ```bash
   nb plugin install nonebot-plugin-feature-switch
   ```

2. 在 `.env` 里至少配置超管：

   ```dotenv
   SUPERUSERS=["<你的QQ>"]
   FEATURE_SWITCH_STATE_PATH=data/feature_switch/state.json
   ```

3. 私聊 bot 发 `/开关 群 <群号> 开` 开启某个群的全部功能，或 `/开关 开 <功能> <群号>` 精细控制。

## 管理命令

| 命令 | 说明 |
|:---:|:---|
| `/开关` | 帮助 |
| `/开关 列表` | 功能列表与默认值 |
| `/开关 矩阵 [功能]` | 功能 × 群矩阵 |
| `/开关 群 <群号> 开\|关` | 一键启停该群所有功能 |
| `/开关 开\|关 <功能\|全部> <群号\|全部>` | 精细控制 |
| `/开关 默认 <功能> 开\|关` | 改功能级默认 |
| `/开关 复位 <功能> <群号>` | 清除显式覆盖 |

## 配置

| 变量 | 默认 | 说明 |
|:---:|:---:|:---|
| `FEATURE_SWITCH_ACTIVE` | `true` | 是否安装门禁（回滚用） |
| `FEATURE_SWITCH_MODE` | `wrap` | `wrap` 推荐；`append` 为降级模式 |
| `FEATURE_SWITCH_STATE_PATH` | `data/feature_switch/state.json` | 状态文件 |
| `FEATURE_SWITCH_TEST_GROUPS` | 空 | 出厂默认放行的群 |
| `SUPERUSERS` | 空 | 超管 QQ，管理命令唯一权限来源 |

## 说明

- 门禁依赖 NoneBot 2.5 的 matcher 内部 API，`nonebot2` 锁定 `>=2.5,<2.6`
- 新插件需要补 `gate.py` 的 `FEATURES` 映射，否则不会被拦截
- 支持外部 WS 消费者 `ws_maimai` / `ws_pjsk` / `ws_misc`（与 `onebot-extproxy` 共用 state.json）

## License

[MIT](./LICENSE)
