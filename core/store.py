"""生理周期数据持久化层（纯存取）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "period_start": "",       # yyyy-mm-dd，空表示尚未设定
    "cycle_length": 28,
    "period_length": 5,
    "history": [],            # 历次经期开始日，最新在末尾
}


class CycleStore:
    """单文件 JSON 存取，状态全局唯一（晚宁本人的身体，与会话无关）。"""

    def __init__(self, json_path: Path):
        self._path = json_path
        self._data: dict[str, Any] = dict(_DEFAULTS)
        self.load()

    # ---------- 读 ----------
    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    @property
    def enabled(self) -> bool:
        return bool(self._data.get("enabled", True))

    @property
    def period_start(self) -> str:
        return str(self._data.get("period_start", "") or "")

    @property
    def cycle_length(self) -> int:
        try:
            return int(self._data.get("cycle_length", 28))
        except (TypeError, ValueError):
            return 28

    @property
    def period_length(self) -> int:
        try:
            return int(self._data.get("period_length", 5))
        except (TypeError, ValueError):
            return 5

    # ---------- 写 ----------
    def set(self, key: str, value: Any) -> None:
        self._data[key] = value
        self.save()

    def set_period_start(self, date_str: str) -> None:
        """设定最近一次经期开始日，并追加到历史（去重、保序、限长）。"""
        date_str = str(date_str or "").strip()
        self._data["period_start"] = date_str
        history = [d for d in self._data.get("history", []) if d != date_str]
        if date_str:
            history.append(date_str)
        self._data["history"] = history[-24:]
        self.save()

    # ---------- 持久化 ----------
    def load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return
        if isinstance(raw, dict):
            merged = dict(_DEFAULTS)
            merged.update(raw)
            self._data = merged

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self._path)
