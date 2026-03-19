from __future__ import annotations

from dataclasses import dataclass

from ortools.sat.python import cp_model

from .model import Assignment, EpicResult, Priority, Seniority, Sprint


PRIORITY_WEIGHTS = {
    Priority.P0: 1000,
    Priority.P1: 100,
    Priority.P2: 10,
    Priority.P3: 1,
}

SENIORITY_OWNER_BONUS = {
    Seniority.SENIOR: 3,
    Seniority.MID: 2,
    Seniority.JUNIOR: 1,
}

MAX_EPICS_PER_ENGINEER = 2


@dataclass
class SolverResult:
    status: str
    assignments: list[Assignment]
    unassigned_epics: list[str]
    engineer_utilization: dict[str, dict]
    epic_results: list[EpicResult]


def solve(sprint: Sprint) -> SolverResult:
    mdl = cp_model.CpModel()

    engineers = {e.id: e for e in sprint.engineers}
    epics = {e.id: e for e in sprint.epics}
    days = list(range(1, sprint.total_days + 1))

    remaining = {eid: e.remaining_days for eid, e in epics.items()}
    # Half-day units: when an engineer works on 2 epics, each gets 1 half-day.
    # Working on 1 epic = 2 half-days = 1 full day of effort.
    remaining_half = {eid: r * 2 for eid, r in remaining.items()}

    # --- Variables ---

    # slot[eng, epic, day] in {0,1,2}: half-day effort units allocated
    slot = {}
    # active[eng, epic, day]: bool, slot > 0
    active = {}
    for eng_id in engineers:
        for eid in epics:
            for d in days:
                slot[eng_id, eid, d] = mdl.new_int_var(0, 2, f"s_{eng_id}_{eid}_{d}")
                active[eng_id, eid, d] = mdl.new_bool_var(f"a_{eng_id}_{eid}_{d}")

    # x[eng, epic]: assigned at all
    x = {}
    # role[eng, epic]: 1 = owner
    role = {}
    for eng_id in engineers:
        for eid in epics:
            x[eng_id, eid] = mdl.new_bool_var(f"x_{eng_id}_{eid}")
            role[eng_id, eid] = mdl.new_bool_var(f"r_{eng_id}_{eid}")

    # epic_effort[epic]: total half-day units received
    epic_effort = {}
    for eid in epics:
        epic_effort[eid] = mdl.new_int_var(0, remaining_half[eid], f"eff_{eid}")

    # has_effort[epic]: receives any effort at all
    has_effort = {}
    for eid in epics:
        has_effort[eid] = mdl.new_bool_var(f"he_{eid}")

    # epic_done[epic, day]: cumulative effort >= remaining by end of day d
    epic_done = {}
    for eid in epics:
        for d in days:
            epic_done[eid, d] = mdl.new_bool_var(f"done_{eid}_{d}")

    # epic_active_day[epic, day]: any engineer works on epic on day d
    epic_active_day = {}
    for eid in epics:
        for d in days:
            epic_active_day[eid, d] = mdl.new_bool_var(f"ead_{eid}_{d}")

    # --- Constraints ---

    # Link slot <-> active
    for eng_id in engineers:
        for eid in epics:
            for d in days:
                mdl.add(slot[eng_id, eid, d] == 0).only_enforce_if(
                    active[eng_id, eid, d].negated()
                )
                mdl.add(slot[eng_id, eid, d] >= 1).only_enforce_if(
                    active[eng_id, eid, d]
                )

    # Per engineer per day: max 2 half-day slots, max 2 active epics
    for eng_id in engineers:
        for d in days:
            mdl.add(sum(slot[eng_id, eid, d] for eid in epics) <= 2)
            mdl.add(sum(active[eng_id, eid, d] for eid in epics) <= MAX_EPICS_PER_ENGINEER)

    # Per engineer: total slots <= capacity * 2
    for eng_id, eng in engineers.items():
        mdl.add(
            sum(slot[eng_id, eid, d] for eid in epics for d in days) <= eng.capacity_days * 2
        )

    # Link x to active (assigned iff active on any day)
    for eng_id in engineers:
        for eid in epics:
            mdl.add_max_equality(x[eng_id, eid], [active[eng_id, eid, d] for d in days])

    # Epic total effort
    for eid in epics:
        mdl.add(
            epic_effort[eid] == sum(slot[eng_id, eid, d] for eng_id in engineers for d in days)
        )

    # has_effort
    for eid in epics:
        mdl.add(epic_effort[eid] >= 1).only_enforce_if(has_effort[eid])
        mdl.add(epic_effort[eid] == 0).only_enforce_if(has_effort[eid].negated())

    # Epic active day
    for eid in epics:
        for d in days:
            mdl.add_max_equality(
                epic_active_day[eid, d],
                [active[eng_id, eid, d] for eng_id in engineers],
            )

    # --- Dynamic completion ---
    # Track when cumulative effort reaches remaining. No work allowed after done.
    for eid in epics:
        rh = remaining_half[eid]
        if rh == 0:
            # Already complete — force no work and done on all days.
            for d in days:
                mdl.add(epic_done[eid, d] == 1)
                for eng_id in engineers:
                    mdl.add(slot[eng_id, eid, d] == 0)
            continue

        for d in days:
            cum = sum(slot[eng_id, eid, dd] for eng_id in engineers for dd in days if dd <= d)
            mdl.add(cum >= rh).only_enforce_if(epic_done[eid, d])
            mdl.add(cum <= rh - 1).only_enforce_if(epic_done[eid, d].negated())

            # No work after done
            if d < sprint.total_days:
                for eng_id in engineers:
                    mdl.add(slot[eng_id, eid, d + 1] == 0).only_enforce_if(epic_done[eid, d])

        # Monotonicity
        for i in range(len(days) - 1):
            mdl.add_implication(epic_done[eid, days[i]], epic_done[eid, days[i + 1]])

    # --- Required engineers ---
    for eid, epic in epics.items():
        assigned_count = [x[eng_id, eid] for eng_id in engineers]
        mdl.add(sum(assigned_count) >= epic.required_engineers).only_enforce_if(has_effort[eid])

    # --- Owner ---
    for eid in epics:
        owner_vars = [role[eng_id, eid] for eng_id in engineers]
        mdl.add(sum(owner_vars) == 1).only_enforce_if(has_effort[eid])
        mdl.add(sum(owner_vars) == 0).only_enforce_if(has_effort[eid].negated())

    for eng_id in engineers:
        for eid in epics:
            mdl.add_implication(role[eng_id, eid], x[eng_id, eid])

    # Owner continuity: owner must be active every day the epic is being worked on.
    for eng_id in engineers:
        for eid in epics:
            for d in days:
                mdl.add(active[eng_id, eid, d] >= 1).only_enforce_if(
                    [role[eng_id, eid], epic_active_day[eid, d]]
                )

    # --- Skill matching ---
    for eng_id, eng in engineers.items():
        eng_skills = set(eng.skills) if eng.skills else set()
        for eid, epic in epics.items():
            req = set(epic.required_skills) if epic.required_skills else set()
            if req and not (eng_skills & req):
                # Engineer lacks required skills — cannot be assigned.
                mdl.add(x[eng_id, eid] == 0)

    # --- Spillover ---
    for eng_id, eng in engineers.items():
        for spill_eid in eng.spillover_epics:
            if spill_eid in epics:
                mdl.add(x[eng_id, spill_eid] == 1)

    # --- Objective ---
    objective_terms = []
    for eid, epic in epics.items():
        # Reward effort proportional to priority
        objective_terms.append(epic_effort[eid] * PRIORITY_WEIGHTS[epic.priority])

        # Seniority bonus for owners (stronger for senior_required)
        mult = 2 if epic.senior_required else 1
        for eng_id, eng in engineers.items():
            objective_terms.append(role[eng_id, eid] * SENIORITY_OWNER_BONUS[eng.seniority] * mult)

    mdl.maximize(sum(objective_terms))

    # --- Solve ---
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 30.0
    status = solver.solve(mdl)

    status_name = {
        cp_model.OPTIMAL: "optimal",
        cp_model.FEASIBLE: "feasible",
        cp_model.INFEASIBLE: "infeasible",
        cp_model.MODEL_INVALID: "infeasible",
        cp_model.UNKNOWN: "infeasible",
    }[status]

    assignments: list[Assignment] = []
    unassigned: list[str] = []
    utilization: dict[str, dict] = {}
    epic_results: list[EpicResult] = []

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        unassigned = list(epics.keys())
        for eng_id, eng in engineers.items():
            utilization[eng_id] = {"capacity": eng.capacity_days, "used": 0.0, "pct": 0.0}
        return SolverResult(status_name, assignments, unassigned, utilization, epic_results)

    # Extract assignments
    for eid, epic in epics.items():
        eff_half = solver.value(epic_effort[eid])
        if eff_half == 0:
            unassigned.append(eid)

        eff_days = eff_half / 2.0
        finish_day = None
        for d in days:
            if solver.value(epic_done[eid, d]):
                finish_day = d
                break

        projected = epic.completion_pct + (eff_days / epic.total_days) if epic.total_days > 0 else 1.0
        projected = min(projected, 1.0)

        epic_results.append(EpicResult(
            epic_id=eid,
            effort_days=eff_days,
            remaining_days=remaining[eid],
            finish_day=finish_day,
            original_completion_pct=epic.completion_pct,
            projected_completion_pct=projected,
        ))

        for eng_id in engineers:
            if not solver.value(x[eng_id, eid]):
                continue
            r = "owner" if solver.value(role[eng_id, eid]) else "implementer"
            start = sprint.total_days + 1
            end = 0
            eng_eff_half = 0
            for d in days:
                if solver.value(active[eng_id, eid, d]):
                    start = min(start, d)
                    end = max(end, d)
                    eng_eff_half += solver.value(slot[eng_id, eid, d])
            assignments.append(Assignment(
                engineer_id=eng_id,
                epic_id=eid,
                role=r,
                start_day=start,
                end_day=end,
                effort_days=eng_eff_half / 2.0,
            ))

    for eng_id, eng in engineers.items():
        used_half = sum(
            solver.value(slot[eng_id, eid, d]) for eid in epics for d in days
        )
        used = used_half / 2.0
        utilization[eng_id] = {
            "capacity": eng.capacity_days,
            "used": used,
            "pct": round(used / eng.capacity_days * 100, 1) if eng.capacity_days > 0 else 0.0,
        }

    return SolverResult(status_name, assignments, unassigned, utilization, epic_results)
