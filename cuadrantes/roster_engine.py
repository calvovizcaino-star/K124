"""K124 roster engine prototype based on Roster Wizard's OR-Tools CP-SAT approach.

This module is deliberately independent from Django and the current browser UI.
It accepts plain Python data and returns a complete roster or a diagnostic.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from ortools.sat.python import cp_model


REGULAR = ("K", "F", "R")
CARLOS = "C"
SHIFTS = ("MANANA", "PARTIDO", "TARDE")


def _dates(start: date, days: int) -> list[date]:
    return [start + timedelta(days=i) for i in range(days)]


def solve_roster(
    start: date,
    days: int,
    vacations: list[dict[str, Any]] | None = None,
    fixed: dict[str, dict[str, str]] | None = None,
    previous_late: dict[str, list[str]] | None = None,
    time_limit_seconds: int = 20,
) -> dict[str, Any]:
    """Solve a roster.

    vacations: [{"person": "K"|"F"|"R"|"C", "from": "YYYY-MM-DD", "to": "YYYY-MM-DD"}]
    fixed: {"YYYY-MM-DD": {"MANANA": "K", ...}}
    previous_late: {"YYYY-MM-DD": ["F"]} for late shifts immediately before start.
    """
    if days < 1:
        raise ValueError("days must be positive")
    vacations = vacations or []
    fixed = fixed or {}
    previous_late = previous_late or {}
    dates = _dates(start, days)
    model = cp_model.CpModel()

    leave: set[tuple[str, date]] = set()
    for item in vacations:
        person = item["person"]
        if person not in REGULAR + (CARLOS,):
            raise ValueError(f"Unknown vacation worker: {person}")
        first = date.fromisoformat(item["from"])
        last = date.fromisoformat(item["to"])
        if last < first:
            raise ValueError(f"Vacation end is before start for {person}")
        for d in dates:
            if first <= d <= last:
                leave.add((person, d))

    def required_shifts(d: date) -> tuple[str, ...]:
        return SHIFTS if d.weekday() == 4 else ("MANANA", "TARDE")

    # Assignment variables. Carlos is only available as a vacation substitute.
    workers = REGULAR + (CARLOS,)
    x = {
        (p, d, s): model.NewBoolVar(f"x_{p}_{d}_{s}")
        for p in workers for d in dates for s in SHIFTS
    }

    for d in dates:
        required = required_shifts(d)
        for s in SHIFTS:
            if s in required:
                model.Add(sum(x[p, d, s] for p in workers) == 1)
            else:
                model.Add(sum(x[p, d, s] for p in workers) == 0)

        for p in workers:
            model.Add(sum(x[p, d, s] for s in SHIFTS) <= 1)

        on_leave = [p for p in REGULAR if (p, d) in leave]
        if (CARLOS, d) in leave:
            model.Add(sum(x[CARLOS, d, s] for s in SHIFTS) == 0)
        for p in on_leave:
            model.Add(sum(x[p, d, s] for s in SHIFTS) == 0)

        # Carlos covers TARDE on vacation days and may cover TARDE on
        # ordinary days when two regular workers rest together. On Fridays
        # he covers PARTIDO only when a regular worker is on vacation.
        if on_leave:
            if len(on_leave) > 1:
                model.AddBoolOr([])
            else:
                substitute_shift = "PARTIDO" if d.weekday() == 4 else "TARDE"
                model.Add(x[CARLOS, d, substitute_shift] == 1)
                model.Add(sum(x[CARLOS, d, s] for s in SHIFTS) == 1)
        elif (CARLOS, d) not in leave:
            if d.weekday() == 4:
                model.Add(sum(x[CARLOS, d, s] for s in SHIFTS) == 0)
            else:
                model.Add(x[CARLOS, d, "MANANA"] == 0)
                model.Add(x[CARLOS, d, "PARTIDO"] == 0)
                regular_assignments = sum(x[p, d, s] for p in REGULAR for s in SHIFTS)
                model.Add(regular_assignments + x[CARLOS, d, "TARDE"] == 2)

        # No morning after an afternoon or partido shift on the previous day.
        prev = d - timedelta(days=1)
        late_yesterday = set(previous_late.get(prev.isoformat(), [])) if prev < start else set()
        for p in REGULAR:
            if p in late_yesterday:
                model.Add(x[p, d, "MANANA"] == 0)
            if prev in dates:
                model.Add(x[p, prev, "PARTIDO"] + x[p, prev, "TARDE"] + x[p, d, "MANANA"] <= 1)

    # Fixed/manual assignments are hard constraints.
    for date_text, assignments in fixed.items():
        d = date.fromisoformat(date_text)
        if d not in dates:
            continue
        for shift, person in assignments.items():
            if shift not in SHIFTS or person not in workers:
                raise ValueError(f"Invalid fixed assignment: {date_text} {shift} {person}")
            model.Add(x[person, d, shift] == 1)

    # Exactly two consecutive rest days per regular worker in each complete
    # Monday-Sunday week. Rest days may coincide across workers; Carlos can
    # cover the afternoon when two regular workers rest on an ordinary day.
    # Vacation days are separate from rest days.
    weeks: dict[date, list[date]] = defaultdict(list)
    for d in dates:
        monday = d - timedelta(days=d.weekday())
        weeks[monday].append(d)
    for monday, week_dates in weeks.items():
        if len(week_dates) != 7 or week_dates[0].weekday() != 0:
            continue
        for p in REGULAR:
            leave_days = sum((p, d) in leave for d in week_dates)
            if leave_days >= 6:
                continue
            rest = {}
            for d in week_dates:
                rest[d] = model.NewBoolVar(f"rest_{p}_{d.isoformat()}")
                if (p, d) in leave:
                    model.Add(rest[d] == 0)
                else:
                    model.Add(
                        sum(x[p, d, s] for s in SHIFTS) + rest[d] == 1
                    )
            model.Add(sum(rest.values()) == 2)
            # The two rest days must be adjacent in the same week.
            adjacent = []
            for i in range(6):
                pair = model.NewBoolVar(f"pair_{p}_{monday}_{i}")
                model.Add(pair <= rest[week_dates[i]])
                model.Add(pair <= rest[week_dates[i + 1]])
                model.Add(pair >= rest[week_dates[i]] + rest[week_dates[i + 1]] - 1)
                adjacent.append(pair)
            model.Add(sum(adjacent) == 1)

    # Sunday rotation: in every complete three-week block, each regular worker
    # must receive at least one Sunday without a shift.
    sundays = [d for d in dates if d.weekday() == 6]
    for i in range(0, len(sundays) - 2, 3):
        block = sundays[i:i + 3]
        for p in REGULAR:
            model.Add(
                sum(sum(x[p, d, s] for s in SHIFTS) for d in block) <= 2
            )

    # Balance the total number of shifts between regular workers (soft objective).
    totals = {
        p: sum(x[p, d, s] for d in dates for s in SHIFTS)
        for p in REGULAR
    }
    max_total = model.NewIntVar(0, days, "max_regular_shifts")
    min_total = model.NewIntVar(0, days, "min_regular_shifts")
    for p in REGULAR:
        model.Add(totals[p] <= max_total)
        model.Add(totals[p] >= min_total)
    model.Minimize((max_total - min_total) * 100)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_seconds
    solver.parameters.num_search_workers = 8
    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {
            "status": "INFEASIBLE" if status == cp_model.INFEASIBLE else "UNKNOWN",
            "message": "No se ha encontrado un cuadrante que cumpla todas las reglas.",
            "conflicts": [
                "Comprueba vacaciones simultáneas: Carlos solo puede cubrir una ausencia al día.",
                "Comprueba turnos fijos que contradigan descansos o el descanso entre jornadas.",
                "Comprueba que el periodo incluya semanas completas para validar los descansos.",
            ],
            "assignments": {},
        }

    result: dict[str, dict[str, str]] = {}
    for d in dates:
        day_result = {}
        for s in required_shifts(d):
            for p in workers:
                if solver.Value(x[p, d, s]):
                    day_result[s] = p
                    break
        result[d.isoformat()] = day_result

    return {
        "status": "OPTIMAL" if status == cp_model.OPTIMAL else "FEASIBLE",
        "message": "Cuadrante calculado.",
        "assignments": result,
        "objective": solver.ObjectiveValue(),
    }
