"""功能开关状态存储。

JSON schema v2（``state.json``）::

    {
      "version": 2,
      "updated_at": "ISO-8601",
      "group_default": false,
      "group_defaults": {"100001": true},
      "feature_defaults": {"music_score_reactor": false},
      "matrix": {"quote_card": {"100002": true}}
    }

生效顺序（四层回落）：``matrix[feature][group]`` → ``feature_defaults[feature]`` →
``group_defaults[group]`` → ``group_default``；``group_id is None``（私聊）永远放行。

设计：
- 单写者（NoneBot 单实例），``asyncio.Lock`` 串行化读-改-写；
- 原子写：tmp → fsync → ``os.replace`` → 目录 fsync；
- 读缓存：``os.stat`` 的 ``st_mtime_ns + st_size`` 命中即不读盘，支持手动改文件热更新；
- 坏文件：保留上一次成功解析的内存状态（last-good），不崩溃；
- 审计：同目录 ``audit.jsonl`` 追加一行/次变更。
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nonebot.log import logger

STATE_VERSION = 2
DEFAULT_STATE_RELATIVE_PATH = Path("data") / "feature_switch" / "state.json"

# 功能级默认值（覆盖「群默认」）：
# - music_score_reactor：首次全局默认不开启，需显式按群开启；
# - ws_maimai/ws_pjsk/ws_misc：外部 WS 消费者默认全转发（纳入矩阵只为支持按群关闭）。
FEATURE_DEFAULTS = {
    "music_score_reactor": False,
    "ws_maimai": True,
    "ws_pjsk": True,
    "ws_misc": True,
}


def state_path_from_env() -> Path:
    raw = os.getenv("FEATURE_SWITCH_STATE_PATH", "").strip()
    return Path(raw).expanduser() if raw else DEFAULT_STATE_RELATIVE_PATH


def test_groups_from_env() -> set[str]:
    """测试群默认列表；未配置时为空（安全默认：不默认开放任何群）。"""
    raw = os.getenv("FEATURE_SWITCH_TEST_GROUPS", "")
    return {group.strip() for group in raw.split(",") if group.strip()}


def default_state() -> dict[str, Any]:
    """出厂默认状态：测试群全开、其它群全关、music 默认关、ws_* 默认开。"""
    return {
        "version": STATE_VERSION,
        "updated_at": None,
        "group_default": False,
        "group_defaults": {gid: True for gid in sorted(test_groups_from_env())},
        "feature_defaults": dict(FEATURE_DEFAULTS),
        "matrix": {},
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class FeatureSwitchStore:
    """功能×群开关矩阵：读缓存 + 四层回落 + 原子写 + 审计。"""

    def __init__(self, path: str | Path | None = None, audit_path: str | Path | None = None):
        self.path = Path(path) if path is not None else state_path_from_env()
        self.audit_path = Path(audit_path) if audit_path else self.path.parent / "audit.jsonl"
        self._lock = asyncio.Lock()
        self._mtime_ns = -1
        self._size = -1
        self._loaded = False
        self._state: dict[str, Any] = default_state()
        self.reload_count = 0
        self.parse_error_count = 0

    # ------------------------------------------------------------------ read
    @staticmethod
    def _normalize(raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise ValueError("state root must be a JSON object")
        st = default_state()
        try:
            st["version"] = int(raw.get("version", STATE_VERSION) or STATE_VERSION)
        except (TypeError, ValueError):
            st["version"] = STATE_VERSION
        updated = raw.get("updated_at")
        st["updated_at"] = updated if isinstance(updated, str) else None
        gd = raw.get("group_default")
        st["group_default"] = gd if isinstance(gd, bool) else st["group_default"]
        gds = raw.get("group_defaults")
        if isinstance(gds, dict):
            st["group_defaults"] = {str(k): bool(v) for k, v in gds.items()}
        fds = raw.get("feature_defaults")
        feature_defaults: dict[str, bool] = {}
        if isinstance(fds, dict):
            feature_defaults = {str(k): bool(v) for k, v in fds.items() if isinstance(v, bool)}
        # 兼容旧 state.json：缺失的新功能默认值用内置 FEATURE_DEFAULTS 补齐（不覆盖显式值）。
        # 只补内存视图，不主动写盘；下一次管理写操作会自然持久化。
        for feature, default in FEATURE_DEFAULTS.items():
            feature_defaults.setdefault(feature, default)
        st["feature_defaults"] = feature_defaults
        mx = raw.get("matrix")
        matrix: dict[str, dict[str, bool]] = {}
        if isinstance(mx, dict):
            for feature, groups in mx.items():
                if not isinstance(groups, dict):
                    continue
                row = {str(gid): bool(v) for gid, v in groups.items() if isinstance(v, bool)}
                if row:
                    matrix[str(feature)] = row
        st["matrix"] = matrix
        return st

    def _load(self) -> dict[str, Any]:
        try:
            st = self.path.stat()
        except OSError:
            if not self._loaded:
                self._state = default_state()
                self._loaded = True
            return self._state
        if st.st_mtime_ns == self._mtime_ns and st.st_size == self._size:
            return self._state
        try:
            raw = json.loads(self.path.read_text("utf-8"))
            self._state = self._normalize(raw)
            self._loaded = True
            self.reload_count += 1
        except (OSError, ValueError, TypeError) as exc:  # 损坏：保留 last-good
            self.parse_error_count += 1
            logger.warning(f"feature_switch: bad state file {self.path}: {exc!r}; keep last-good")
            self._loaded = True
        self._mtime_ns, self._size = st.st_mtime_ns, st.st_size
        return self._state

    def snapshot(self) -> dict[str, Any]:
        return json.loads(json.dumps(self._load(), ensure_ascii=False))  # 深拷贝，防外部改缓存

    def is_enabled(self, feature: str, group_id: str | int | None) -> bool:
        """(功能, 群) 是否开放；私聊/非群事件（group_id=None）永远放行。"""
        if group_id is None:
            return True
        st = self._load()
        gid = str(group_id)
        row = st["matrix"].get(feature) or {}
        if gid in row:
            return bool(row[gid])
        if feature in st["feature_defaults"]:
            return bool(st["feature_defaults"][feature])
        return bool(st["group_defaults"].get(gid, st["group_default"]))

    def source_of(self, feature: str, group_id: str | int) -> str:
        st = self._load()
        gid = str(group_id)
        if gid in (st["matrix"].get(feature) or {}):
            return "矩阵显式"
        if feature in st["feature_defaults"]:
            return "功能默认"
        return "群默认"

    def groups_of(self, feature: str) -> dict[str, bool]:
        return dict(self._load()["matrix"].get(feature) or {})

    def features_of(self, group_id: str | int) -> dict[str, Any]:
        gid = str(group_id)
        st = self._load()
        features = set(st["matrix"]) | set(st["feature_defaults"])
        return {f: {"enabled": self.is_enabled(f, gid), "source": self.source_of(f, gid)} for f in sorted(features)}

    def feature_defaults(self) -> dict[str, bool]:
        return dict(self._load()["feature_defaults"])

    def group_defaults(self) -> dict[str, Any]:
        st = self._load()
        return {"default": st["group_default"], "groups": dict(st["group_defaults"])}

    # ----------------------------------------------------------------- write
    def _write(self, st: dict[str, Any], actor: str, action: str, detail: dict[str, Any]) -> None:
        st["version"] = STATE_VERSION
        st["updated_at"] = _now_iso()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps(st, ensure_ascii=False, indent=2) + "\n"
        tmp = self.path.with_name(f".{self.path.name}.tmp.{os.getpid()}")
        with open(tmp, "w", encoding="utf-8") as fp:
            fp.write(data)
            fp.flush()
            os.fsync(fp.fileno())
        os.replace(tmp, self.path)
        try:  # 目录 fsync，尽量保证 rename 落盘（失败不影响正确性）
            dfd = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        except OSError:
            pass
        stat = self.path.stat()
        self._mtime_ns, self._size = stat.st_mtime_ns, stat.st_size
        self._state = st
        self._loaded = True
        record = {
            "ts": _now_iso(),
            "actor": str(actor),
            "action": action,
            **detail,
            "source": "private-chat",
            "updated_at": st["updated_at"],
        }
        try:
            self.audit_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.audit_path, "a", encoding="utf-8") as fp:
                fp.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as exc:  # 审计失败不影响主流程
            logger.warning(f"feature_switch: write audit failed: {exc!r}")

    def _merge(self) -> dict[str, Any]:
        """从当前 last-good 复制一份可修改副本（保持默认结构）。"""
        st = self._load()
        out = default_state()
        out["version"] = STATE_VERSION
        out["updated_at"] = st["updated_at"]
        out["group_default"] = st["group_default"]
        out["group_defaults"] = dict(st["group_defaults"])
        out["feature_defaults"] = dict(st["feature_defaults"])
        out["matrix"] = {k: dict(v) for k, v in st["matrix"].items()}
        return out

    @staticmethod
    def _effective(st: dict[str, Any], feature: str, group_id: str) -> bool:
        row = st["matrix"].get(feature) or {}
        if group_id in row:
            return bool(row[group_id])
        if feature in st["feature_defaults"]:
            return bool(st["feature_defaults"][feature])
        return bool(st["group_defaults"].get(group_id, st["group_default"]))

    async def set_many(self, features: list[str], groups: list[str], enabled: bool, actor: str) -> list[tuple[str, str, bool, bool]]:
        async with self._lock:
            st = self._merge()
            changes: list[tuple[str, str, bool, bool]] = []
            for feature in features:
                row = st["matrix"].setdefault(feature, {})
                for gid in groups:
                    before = self._effective(st, feature, gid)
                    row[gid] = bool(enabled)
                    changes.append((feature, gid, before, bool(enabled)))
            self._write(
                st, actor, "开" if enabled else "关",
                {"changes": [{"feature": f, "group": g, "before": b, "after": a} for f, g, b, a in changes]},
            )
            return changes

    async def set_global(self, features: list[str], enabled: bool, actor: str) -> list[tuple[str, str, bool, bool]]:
        """全局语义：改功能级默认，并把已知群（测试群 + 矩阵/群默认中出现过的群）显式置为同一状态。"""
        async with self._lock:
            st = self._merge()
            known_groups: set[str] = set(test_groups_from_env())
            known_groups.update(st["group_defaults"])
            for groups in st["matrix"].values():
                known_groups.update(groups)
            changes: list[tuple[str, str, bool, bool]] = []
            for feature in features:
                st["feature_defaults"][feature] = bool(enabled)
                row = st["matrix"].setdefault(feature, {})
                for gid in sorted(known_groups):
                    before = self._effective(st, feature, gid)
                    row[gid] = bool(enabled)
                    changes.append((feature, gid, before, bool(enabled)))
            self._write(
                st, actor, "全局" + ("开" if enabled else "关"),
                {
                    "features": list(features),
                    "groups": sorted(known_groups),
                    "changes": [{"feature": f, "group": g, "before": b, "after": a} for f, g, b, a in changes],
                },
            )
            return changes

    async def reset(self, feature: str, group_id: str, actor: str) -> tuple[bool, bool]:
        async with self._lock:
            st = self._merge()
            before = self._effective(st, feature, group_id)
            row = st["matrix"].get(feature) or {}
            row.pop(group_id, None)
            if row:
                st["matrix"][feature] = row
            else:
                st["matrix"].pop(feature, None)
            after = self._effective(st, feature, group_id)
            self._write(
                st, actor, "复位",
                {"changes": [{"feature": feature, "group": group_id, "before": before, "after": after}]},
            )
            return before, after

    async def set_feature_default(self, feature: str, enabled: bool, actor: str) -> bool | None:
        async with self._lock:
            st = self._merge()
            before = st["feature_defaults"].get(feature)
            st["feature_defaults"][feature] = bool(enabled)
            self._write(st, actor, "默认", {"feature": feature, "before": before, "after": bool(enabled)})
            return before
