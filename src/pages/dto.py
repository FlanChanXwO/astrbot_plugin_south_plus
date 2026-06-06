"""Plugin Pages 响应 DTO 转换。"""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from typing import Any

from ..core.datamodels import (
    CheckinRow,
    GroupRow,
    ScheduleRow,
    UserGroupRow,
    UserRow,
)


def ok_response(**payload: Any) -> dict[str, Any]:
    """构造统一成功响应。"""
    return {"ok": True, **payload}


def error_response(message: str) -> dict[str, Any]:
    """构造统一失败响应。"""
    return {"ok": False, "message": message}


def user_to_public_dict(row: UserRow) -> dict[str, Any]:
    """账号行脱敏输出，严禁返回明文 cookie。"""
    payload = row.to_public_dict()
    payload.pop("cookie", None)
    return payload


def group_to_dict(row: GroupRow) -> dict[str, Any]:
    return _dataclass_to_dict(row)


def user_group_to_dict(row: UserGroupRow) -> dict[str, Any]:
    return _dataclass_to_dict(row)


def schedule_to_dict(row: ScheduleRow) -> dict[str, Any]:
    payload = _dataclass_to_dict(row)
    payload["params"] = parse_params_json(row.params_json)
    return payload


def checkin_to_dict(row: CheckinRow) -> dict[str, Any]:
    return _dataclass_to_dict(row)


def parse_params_json(value: str) -> dict[str, Any]:
    """解析调度参数 JSON；失败时保留空对象并让原文继续展示。"""
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _dataclass_to_dict(row: Any) -> dict[str, Any]:
    if is_dataclass(row):
        return asdict(row)
    return dict(row)
