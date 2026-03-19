from __future__ import annotations

import json
import sys

from .model import Engineer, Epic, Priority, Seniority, Sprint
from .solver import solve


def load_sprint(path: str) -> Sprint:
    with open(path) as f:
        data = json.load(f)

    engineers = [
        Engineer(
            id=e["id"],
            name=e["name"],
            seniority=Seniority[e["seniority"].upper()],
            capacity_days=e["capacity_days"],
            skills=e.get("skills", []),
            spillover_epics=e.get("spillover_epics", []),
        )
        for e in data["engineers"]
    ]

    epics = [
        Epic(
            id=ep["id"],
            name=ep["name"],
            priority=Priority[ep["priority"].upper()],
            total_days=ep["total_days"],
            completion_pct=ep.get("completion_pct", 0.0),
            required_engineers=ep.get("required_engineers", 1),
            senior_required=ep.get("senior_required", False),
            required_skills=ep.get("required_skills", []),
            is_spillover=ep.get("is_spillover", False),
        )
        for ep in data["epics"]
    ]

    return Sprint(
        name=data["sprint_name"],
        total_days=data["sprint_days"],
        engineers=engineers,
        epics=epics,
    )


def format_result(sprint: Sprint, result) -> str:
    engineers = {e.id: e for e in sprint.engineers}
    epics = {e.id: e for e in sprint.epics}

    lines = [f"Sprint: {sprint.name} ({sprint.total_days} days)", f"Status: {result.status}", ""]

    # Epic results
    lines.append("== Epic Progress ==")
    for er in sorted(result.epic_results, key=lambda r: epics[r.epic_id].priority):
        epic = epics[er.epic_id]
        orig_pct = round(er.original_completion_pct * 100)
        proj_pct = round(er.projected_completion_pct * 100)
        status = ""
        if er.effort_days == 0:
            status = "NOT STAFFED"
        elif er.finish_day is not None:
            status = f"done day {er.finish_day}"
        else:
            status = "partial"
        lines.append(
            f"  {epic.name} ({epic.priority.name}): "
            f"{er.effort_days:.1f}/{er.remaining_days}d effort | "
            f"{orig_pct}% -> {proj_pct}% | {status}"
        )

    # Assignments grouped by engineer
    lines.append("\n== Assignments ==")
    by_eng: dict[str, list] = {e.id: [] for e in sprint.engineers}
    for a in result.assignments:
        by_eng[a.engineer_id].append(a)

    for eng_id, eng in engineers.items():
        util = result.engineer_utilization.get(eng_id, {})
        lines.append(
            f"\n{eng.name} ({eng.seniority.name}"
            f"{', ' + '/'.join(eng.skills) if eng.skills else ''}, "
            f"{util.get('used', 0)}/{eng.capacity_days}d, "
            f"{util.get('pct', 0)}%)"
        )
        eng_assignments = by_eng.get(eng_id, [])
        if not eng_assignments:
            lines.append("  (idle)")
            continue
        for a in sorted(eng_assignments, key=lambda a: a.start_day):
            epic = epics[a.epic_id]
            lines.append(
                f"  [{a.role.upper():12s}] {epic.name} ({epic.priority.name}) "
                f"day {a.start_day}-{a.end_day}, {a.effort_days:.1f}d effort"
            )

    if result.unassigned_epics:
        lines.append("\n== Unassigned Epics ==")
        for eid in result.unassigned_epics:
            epic = epics[eid]
            lines.append(f"  {epic.name} ({epic.priority.name}, {epic.remaining_days}d remaining)")

    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        print("Usage: task-constraint <sprint.json>", file=sys.stderr)
        sys.exit(1)

    sprint = load_sprint(sys.argv[1])
    result = solve(sprint)
    print(format_result(sprint, result))


if __name__ == "__main__":
    main()
