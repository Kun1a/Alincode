"""记忆类型定义（T9）。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class NoteType(StrEnum):
    USER_PREFERENCE = "user_preference"
    CORRECTION_FEEDBACK = "correction_feedback"
    PROJECT_KNOWLEDGE = "project_knowledge"
    REFERENCE_MATERIAL = "reference_material"


@dataclass
class Note:
    type: NoteType
    title: str
    slug: str
    content: str
    filename: str  # 形如 "user_preference_terse_replies.md"
    created: datetime
    updated: datetime


@dataclass
class UpdateAction:
    action: str       # "create" / "update" / "delete"
    level: str        # "project" / "user"
    type: str = ""    # NoteType（create 时必需）
    title: str = ""
    slug: str = ""
    content: str = ""
    filename: str = ""  # update/delete 时必需
