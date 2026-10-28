"""자리뽑기 순수 로직 (DB·HTTP 없음)."""
from dataclasses import dataclass, field

from app.domains.game.rng import SeededRandom

PREVIOUS_SEAT_ATTEMPTS = 100


@dataclass
class SeatPlan:
    rows: int
    cols: int
    disabled: set[tuple[int, int]]
    students: list[int]  # 배치할 학생 번호
    fixed: dict[int, tuple[int, int]] = field(default_factory=dict)  # 번호 -> (행, 열) 고정 자석
    avoid_previous: bool = False
    previous: dict[int, tuple[int, int]] = field(default_factory=dict)  # 번호 -> 직전 자리


@dataclass
class SeatOutcome:
    placements: list[tuple[int, int, int, bool]]  # (행, 열, 번호, 고정 여부) 행·열 순
    empty: list[tuple[int, int]]
    warnings: list[str]


def available_seats(plan: SeatPlan) -> list[tuple[int, int]]:
    return [(r, c) for r in range(1, plan.rows + 1) for c in range(1, plan.cols + 1) if (r, c) not in plan.disabled]


def assign_seats(seed: str, plan: SeatPlan) -> SeatOutcome:
    """고정 자석 학생을 먼저 배치하고, 나머지 학생(번호순)을 섞은 남은 자리에 앉힌다."""
    seats = available_seats(plan)
    fixed_seats = set(plan.fixed.values())
    free_seats = [s for s in seats if s not in fixed_seats]
    free_students = sorted(n for n in plan.students if n not in plan.fixed)

    rng = SeededRandom(seed)
    best: dict[int, tuple[int, int]] = {}
    best_conflicts: int | None = None
    for _ in range(PREVIOUS_SEAT_ATTEMPTS if plan.avoid_previous else 1):
        placed = dict(zip(free_students, rng.shuffle(free_seats)))
        conflicts = sum(1 for n, s in placed.items() if plan.previous.get(n) == s) if plan.avoid_previous else 0
        if best_conflicts is None or conflicts < best_conflicts:
            best, best_conflicts = placed, conflicts
        if conflicts == 0:
            break

    warnings = ["PREVIOUS_SEAT_UNAVOIDABLE"] if plan.avoid_previous and best_conflicts else []
    placements = [(s[0], s[1], n, False) for n, s in best.items()]
    placements += [(s[0], s[1], n, True) for n, s in plan.fixed.items()]
    placements.sort()
    used = {(p[0], p[1]) for p in placements}
    return SeatOutcome(placements, [s for s in seats if s not in used], warnings)
