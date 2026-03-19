from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import IntEnum


class Priority(IntEnum):
    P0 = 0
    P1 = 1
    P2 = 2
    P3 = 3


class Seniority(IntEnum):
    JUNIOR = 0
    MID = 1
    SENIOR = 2


@dataclass
class Engineer:
    id: str
    name: str
    seniority: Seniority
    capacity_days: int  # available days this sprint (accounts for PTO etc)
    skills: list[str] = field(default_factory=list)
    spillover_epics: list[str] = field(default_factory=list)


@dataclass
class Epic:
    id: str
    name: str
    priority: Priority
    total_days: int  # total implementation effort in days
    completion_pct: float = 0.0  # 0.0 - 1.0
    required_engineers: int = 1
    senior_required: bool = False
    required_skills: list[str] = field(default_factory=list)
    is_spillover: bool = False

    @property
    def remaining_days(self) -> int:
        return math.ceil(self.total_days * (1 - self.completion_pct))


@dataclass
class Assignment:
    engineer_id: str
    epic_id: str
    role: str  # "owner" or "implementer"
    start_day: int
    end_day: int
    effort_days: float  # actual effort contributed in days


@dataclass
class EpicResult:
    epic_id: str
    effort_days: float  # effort contributed this sprint
    remaining_days: int  # remaining before sprint
    finish_day: int | None  # day epic completes, or None if partial
    original_completion_pct: float
    projected_completion_pct: float  # at sprint end


@dataclass
class Sprint:
    name: str
    total_days: int
    engineers: list[Engineer] = field(default_factory=list)
    epics: list[Epic] = field(default_factory=list)
