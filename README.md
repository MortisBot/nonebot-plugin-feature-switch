# nonebot-plugin-feature-switch

> 同系列插件与部署/架构文档：[`MortisBot/qqbot-plugins`](https://github.com/MortisBot/qqbot-plugins)（索引与文档仓）

按「功能 × 群」控制已安装插件是否响应。它不修改业务插件源码，而是在启动时找到
matcher，把 `rule` 包一层门禁：群聊里功能关闭时规则短路，私聊永远放行。

- 管理仅限超管（`SUPERUSERS`）**私聊**；群聊中静默忽略。
- 默认安全：`FEATURE_SWITCH_TEST_GROUPS` 为空，所有群默认关闭；
  `music_score_reactor` 功能级默认关。
- 外部 WS 消费者（`ws_maimai` / `ws_pjsk` / `ws_misc`）没有 matcher，
  由外部中继读取同一份 `state.json` 按群过滤，默认全转发。
- `ping` 常开，只用于连通性诊断。

## 安装

```bash
nb plugin install nonebot-plugin-feature-switch
```

需要 NoneBot 2.5.x（`nonebot2>=2.5,<2.6`）与 OneBot v11 适配器。

## 功能 key

| key | 说明 | 默认 |
|---|---|---|
| `quote_card` | 引用消息卡片 | 群默认 |
| `mface_pool` | 表情池（收集/概率发送） | 群默认 |
| `group_rank` | 群排行（精华榜/发言榜） | 群默认 |
| `imitate` | 模仿 | 群默认 |
| `chart_download` | 谱面下载/索引/别名（覆盖 chart 三件套模块） | 群默认 |
| `music_score_reactor` | 成绩图贴表情 | 功能级关 |
| `ws_maimai` | 外部 WS 消费者：maimai | 功能级开 |
| `ws_pjsk` | 外部 WS 消费者：pjsk | 功能级开 |
| `ws_misc` | 外部 WS 消费者：misc | 功能级开 |
| `ping` | 连通性诊断 | 常开，不纳管 |

模块名映射兼容 `plugins.chart_download`、`nonebot_plugin_chart_downloader.download` 等布局；
新插件可用 `FEATURE_SWITCH_MODULE_MAP` 补充匹配词，无需改代码。

## 配置

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `FEATURE_SWITCH_ACTIVE` | `true` | `false` 时不安装门禁、不注册管理命令 |
| `FEATURE_SWITCH_STATE_PATH` | `data/feature_switch/state.json` | 状态文件路径 |
| `FEATURE_SWITCH_MODE` | `wrap` | `wrap`=替换 rule 短路；`append`=追加 checker 的降级模式 |
| `FEATURE_SWITCH_TEST_GROUPS` | 空 | 默认开放的群，逗号分隔；**空=没有群默认开放** |
| `FEATURE_SWITCH_MODULE_MAP` | 空 | JSON：`{"功能key": ["额外模块名匹配词", ...]}` |
| `SUPERUSERS` | NoneBot 标准 | 管理命令唯一权限来源，例如 `["<管理员QQ>"]` |

`FEATURE_SWITCH_TEST_GROUPS` 只影响出厂默认与回落值；运行期以 `state.json` 为准。
群聊/非超管发管理命令不会产生任何回复。

## 管理命令（仅私聊 + 超管）

```text
私聊发 help / /help / 帮助 / ?     功能列表 + 命令一览
/开关                              帮助
/开关 列表                         功能列表与显式开关
/开关 矩阵 [功能]                  功能×群矩阵
/开关 查群 <群号>                  某群各功能状态（含来源）
/开关 查 <功能>                    某功能显式开/关的群
/开关 群 <群号> 开|关              一键启停该群全部可关功能（只带群号=查看）
/开关 群开 <群号> / 群关 <群号>    同上（简写）
/开关 开|关 <功能|全部> <群号|全部>[,...]
/开关 批量 <开|关> <功能列表> <群号列表>
/开关 默认 <功能> <开|关>          修改功能级默认
/开关 复位 <功能> <群号>           清除显式覆盖，回落默认
/开关 确认 <token>                 危险操作二次确认（60 秒）
/开关 取消
```

包含 `全部` 或目标群数 > 3 的操作会先返回摘要与 token，需在 60 秒内确认。

## 状态文件（v2）

```json
{
  "version": 2,
  "updated_at": null,
  "group_default": false,
  "group_defaults": {"100001": true},
  "feature_defaults": {
    "music_score_reactor": false,
    "ws_maimai": true,
    "ws_pjsk": true,
    "ws_misc": true
  },
  "matrix": {"quote_card": {"100002": true}}
}
```

生效顺序（四层回落）：

1. `matrix[功能][群]` 显式值；
2. `feature_defaults[功能]` 功能级默认；
3. `group_defaults[群]` 群默认；
4. `group_default` 全局默认。

`group_id is None`（私聊）永远放行。状态文件按 `mtime + size` 热更新，手工编辑后下一条
消息即生效；变更同时追加到同目录 `audit.jsonl`。写入使用临时文件 + `fsync` + `os.replace`，
坏文件会保留上一次成功解析的 last-good 状态，不会导致 bot 崩溃。

## 隐私

- 状态文件与审计日志只保存在本地，包含群 ID 与操作者 ID（超管），不包含消息内容。
- 插件本身不联网、不上报遥测；门禁只读取本地 JSON。
- 请限制 `state.json` / `audit.jsonl` 的读取权限；公开日志或状态前先脱敏群号/账号。
- 管理命令只接受私聊超管，群聊与普通用户不会得到任何反馈。

## 维护与回滚

- 临时停用门禁：`FEATURE_SWITCH_ACTIVE=false` 后重启。
- 恢复默认：删除状态文件（回落出厂默认），下一条消息热更新。
- 退回保守模式：`FEATURE_SWITCH_MODE=append`；原 rule 仍会执行，只作为 NoneBot
  内部 API 变化时的降级路径。
- 新增插件：在 `gate.FEATURES` 增加 key/匹配词，或用 `FEATURE_SWITCH_MODULE_MAP` 临时补充。
- 未映射到功能 key 的插件不会被拦截（按设计只管理清单内功能）。
- 运行期动态创建且启动后才注册的 matcher，由 `on_bot_connect` 重扫兜底。

## License

MIT
