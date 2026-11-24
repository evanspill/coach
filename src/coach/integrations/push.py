"""`coach push`: the only thing that writes to Hevy / Intervals.icu. It always re-validates first and refuses
invalid plans, no matter who calls it. Dry-run unless config/coach.yaml push.enabled is true."""

import datetime as dt
from typing import Any

from coach.coaching.context import Context
from coach.engine.paces import PACE_FACTORS
from coach.engine.prescribe import belt_for, rest_for
from coach.engine.units import lb_to_kg
from coach.engine.validator import Violation, validate_session, validate_week
from coach.integrations.base import Sources
from coach.models import Session, WeekPlan
from coach.models.library import SIDES

RUN_TYPES = {"run_easy", "run_long", "run_quality", "race", "test"}


METCON_TITLE = "Metcon"
TIMED_GENERIC = {"warm up", "stretching"}  # Hevy's generic exercises are timed: reps go in the note
EQUIPMENT = {
    "barbell": "barbell",
    "safety_squat_bar": "barbell",
    "trap_bar": "barbell",
    "dumbbell": "dumbbell",
    "kettlebell": "kettlebell",
    "machine": "machine",
    "cable": "machine",
    "band": "resistance_band",
}
MUSCLE = {"quads": "quadriceps", "core": "abdominals", "back": "upper_back"}


# Routine folders (DECISIONS 103): the current week, one archive per block, and the standing routines. Hevy
# folders are one level deep and nothing can be deleted through the API, so older weeks are moved, never deleted.
FOLDER_THIS_WEEK = "This week (coach)"
FOLDER_STANDING = "Standing (coach)"


def archive_folder_title(ctx: Context, day: dt.date) -> str:
    macro = ctx.macro
    if macro is not None and macro.baseline_start <= day <= macro.baseline_end:
        return "Baseline (coach)"
    blk = macro.block_for(day) if macro else None
    if blk is None:  # before the season, after it, or a gap in it
        return "Other (coach)"
    num = blk.key[1:] if blk.key[:1] == "B" and blk.key[1:].isdigit() else blk.key
    return f"Block {num} (coach)"


class FolderResolver:
    """Folder title -> Hevy folder id: from push_ids, else an existing folder of that title, else a new one.
    Dry runs only report the folders they would create."""

    def __init__(self, hevy, ids: dict, read_only: bool = False):
        self.hevy, self.ids, self.read_only = hevy, ids, read_only
        self.existing: dict[str, str] | None = None
        self.would_create: list[str] = []

    def resolve(self, title: str):
        key = f"hevy-folder:{title}"
        if self.ids.get(key):
            return _folder_id(self.ids[key])
        if self.hevy is None or self.read_only:
            if title not in self.would_create:
                self.would_create.append(title)
            return None
        if self.existing is None:
            self.existing = self.hevy.folders()
        fid = self.existing.get(title) or self.hevy.create_folder(title)
        self.existing[title] = self.ids[key] = str(fid)
        return _folder_id(fid)


def _folder_id(fid):
    s = str(fid)
    return int(s) if s.isdigit() else s


def archive_routines(
    ids: dict, folders: FolderResolver, ctx: Context, sources: Sources | None, before: dt.date, dry_run: bool
) -> list[dict]:
    """Move the routines of sessions dated before `before` out of the current-week folder into their block's
    archive folder. Idempotent (each moved routine is marked in push_ids); a routine deleted in the app is skipped."""
    moved: list[dict] = []
    for key, rid in list(ids.items()):
        if not key.startswith("hevy:") or key.startswith(f"hevy:{STANDING_PREFIX}"):
            continue
        sid = key[len("hevy:") :]
        try:
            day = dt.date.fromisoformat(sid[:10])
        except ValueError:
            continue
        if day >= before or ids.get(f"hevy-archived:{sid}"):
            continue
        title = archive_folder_title(ctx, day)
        if dry_run or sources is None:
            moved.append({"session": sid, "folder": title})
            continue
        try:  # housekeeping: a failed move is reported and retried next push, never blocks today's push
            fid = folders.resolve(title)
            ok = sources.hevy.move_routine(rid, fid)
        except Exception as e:  # noqa: BLE001
            moved.append({"session": sid, "folder": title, "error": str(e)[:200]})
            continue
        ids[f"hevy-archived:{sid}"] = title if ok else "gone (deleted in Hevy)"
        moved.append({"session": sid, "folder": title if ok else None})
    return moved


class TemplateResolver:
    """Hevy needs an exercise_template_id per exercise. Titles come from the library (`hevy_title`, else the name);
    missing ones become custom exercises on first use only (free accounts allow 7). Dry runs only report."""

    def __init__(self, hevy=None, read_only: bool = False):
        self.hevy = hevy
        self.read_only = read_only  # dry run: look titles up in the catalog, create nothing
        self.catalog: dict[str, str] | None = None
        self.created: list[str] = []
        self.would_create: list[str] = []

    def _ids(self) -> dict[str, str]:
        if self.catalog is None:
            self.catalog = self.hevy.template_ids() if self.hevy else {}
        return self.catalog

    def resolve(self, title: str, exercise_type: str, equipment: str, muscle: str) -> str | None:
        tid = self._ids().get(title.lower())
        if tid:
            return tid
        if self.hevy is None or self.read_only:
            if title not in self.would_create:
                self.would_create.append(title)
            return None
        tid = self.hevy.create_template(title, exercise_type, equipment, muscle)
        self._ids()[title.lower()] = tid
        self.created.append(title)
        return tid


# A test's scoring decides how its exercise must be logged (a broad jump is a distance, a hold a duration).
SCORING_TYPE = {"best_of": "short_distance_weight", "max_hold": "duration", "max_reps": "reps_only"}


def _plain(name: str) -> str:
    """'Band pull-apart' == 'Band Pullaparts': letters only, no trailing plural."""
    return "".join(c for c in name.lower() if c.isalnum()).rstrip("s")


def _custom_spec(ex, it, tests=None) -> tuple[str, str, str]:
    scored = next(
        (
            SCORING_TYPE[t.scoring]
            for t in (tests or {}).values()
            if t.session.get("exercise") == ex.id and t.scoring in SCORING_TYPE
        ),
        None,
    )
    if scored:
        kind = scored
    elif it.duration_s is not None:
        kind = "duration"
    elif it.distance_m is not None:
        kind = "short_distance_weight"
    elif ex.load_mode == "bodyweight":
        kind = "reps_only"
    else:
        kind = "weight_reps"
    equipment = EQUIPMENT.get(ex.implement or "", "none" if ex.load_mode == "bodyweight" else "other")
    first = (ex.muscles or ["other"])[0]
    muscle = "lower_back" if first == "back" and "isometric" in ex.tags else MUSCLE.get(first, first)
    return kind, equipment, muscle


class PushRefused(Exception):
    def __init__(self, violations: list[Violation]):
        super().__init__("push refused: plan fails validation")
        self.violations = violations


def hevy_kg(load_kg: float, load_lb: float | None, pair: int = 1) -> float:
    """Hevy's API takes kg only and the app converts back to the athlete's unit. Send the exact conversion of the
    pound load (not kg rounded to 0.1, which shows as 235.01 lb), so the app shows whole pounds (DECISIONS 107)."""
    if load_lb is not None:
        return round(lb_to_kg(load_lb * pair), 9)
    return round(load_kg * pair, 2)


def hevy_routine(
    s: Session, ctx: Context, resolver: TemplateResolver | None = None, folder_id=None
) -> dict | None:
    lib = ctx.cfg.library
    resolver = resolver or TemplateResolver()
    exercises: list[dict[str, Any]] = []
    next_superset = 0
    rules = ctx.cfg.training.rules
    pair_total = ctx.cfg.settings.pair_weight_logging == "total"
    for b in s.blocks:
        if b.metcon is not None:
            mc = b.metcon
            moves = "; ".join(
                f"{getattr(lib.get(m.exercise_id), 'name', m.exercise_id)} "
                + " ".join(
                    x
                    for x in [
                        f"{m.reps} reps" if m.reps else "",
                        f"{m.calories} cal" if m.calories else "",
                        f"{m.distance_m} m" if m.distance_m else "",
                        m.load_note or "",
                    ]
                    if x
                )
                for m in mc.movements
            )
            exercises.append(
                {
                    "exercise_template_id": resolver.resolve(METCON_TITLE, "duration", "other", "full_body"),
                    "notes": f"METCON: {mc.name}. {mc.format.upper()} {mc.time_cap_min:g} min cap. {moves}. Stimulus: {mc.stimulus}. Scaling: {mc.scaling}. "
                    "Log your score in the workout notes (e.g. 'score 5+7 rpe 8').",
                    "sets": [{"type": "normal", "duration_seconds": int(mc.time_cap_min * 60)}],
                }
            )
            continue
        for it in b.items:
            ex = lib.get(it.exercise_id)
            if ex is None or b.kind == "cooldown" and ex.id == "easy_cooldown":
                continue
            inches = ex.hevy_log == "inches"
            test = ctx.cfg.tests.tests.get(b.test_id) if b.kind == "test" and b.test_id else None
            # calorie efforts (a calorie-scored test, or a prescription in calories) go in the reps box of a
            # reps-only '<name> (cal)' exercise: Hevy has no calories field
            calories = it.calories is not None or (
                test is not None and test.unit == "cal" and test.session.get("exercise") == ex.id
            )
            # a pair of DBs/KBs is logged as the total of both when the athlete logs that way (Whoop style)
            pair = ex.implements if pair_total else 1
            sets: list[dict[str, Any]] = [
                {"type": "warmup", "reps": r.reps}
                | ({"weight_kg": hevy_kg(r.load_kg, r.load_lb, pair)} if r.load_kg is not None else {})
                for r in it.ramp
            ]
            for _ in range(it.sets):
                st: dict = {
                    "type": "warmup" if b.kind in {"warmup", "cooldown"} else "normal"
                }  # Hevy has no cooldown type
                if it.load_kg is not None:
                    st["weight_kg"] = hevy_kg(it.load_kg, it.load_lb, pair)
                if calories:
                    if it.calories is not None:  # the target, prefilled; a max-effort test leaves it empty
                        st["reps"] = it.calories
                    sets.append(st)
                    continue
                if it.reps is not None and not inches:  # inch-logged: the reps box is the measurement
                    st["reps"] = it.reps
                if it.duration_s is not None:
                    st["duration_seconds"] = it.duration_s
                if it.distance_m is not None and not inches:
                    st["distance_meters"] = it.distance_m
                sets.append(st)
            title = ex.hevy_name(calories=calories)
            timed_generic = title.lower() in TIMED_GENERIC and it.duration_s is None
            # block notes (e.g. the movement screen) on its first item; a test's procedure only when the plan
            # didn't already write this item's own instructions (e.g. "RPE 8, not 9")
            procedure = test.protocol.get("procedure", "") if test and not it.notes else ""
            block_notes = "" if test and it.notes else b.notes
            protocol = (block_notes or procedure) if it is b.items[0] else ""
            belt = belt_for(b.kind, ex, it, rules)
            rest = rest_for(b.kind, ex, it, rules)
            total = (
                f"log {it.load_lb * pair:g} lb total ({pair} x {it.load_lb:g})"
                if pair > 1 and it.load_lb
                else ""
            )
            how_to = " ".join(
                x for x in [ex.description or "", ex.video_url and f"Video: {ex.video_url}"] if x
            )
            if it.notes and (
                (ex.video_url and ex.video_url in it.notes)
                or (ex.description and ex.description[:40] in it.notes)
            ):
                how_to = ""  # the plan's own note already carries the how-to: never print it twice
            alternating = it.per_side and ex.alternates(it.alternating)
            count = (
                f"{it.reps} reps"
                if it.reps
                else (
                    _mmss(it.duration_s)
                    if it.duration_s
                    else f"{it.distance_m} m"
                    if it.distance_m
                    else "reps"
                )
            )
            sides_cue = ex.sides_cue(alternating, count) if it.per_side else ""
            note = " | ".join(
                x
                for x in [
                    # the coach's exercise when Hevy's differs ("Trap bar deadlift (high handle)" in "Deadlift (Trap bar)")
                    ex.name
                    if _plain(ex.name) != _plain(ex.hevy_title or ex.name) and not (inches or calories)
                    else "",
                    "Log the measurement in inches in the reps box" if inches and not calories else "",
                    "Log calories in the reps box"
                    + (f" ({_mmss(it.duration_s)} effort)" if it.duration_s else "")
                    if calories
                    else "",
                    f"{it.reps} reps"
                    if timed_generic and it.reps
                    else "",  # a timed Hevy exercise shows no reps
                    f"{it.rir:g} RIR" if it.rir is not None else "",
                    "" if (it.load_note or "").lower() == "bodyweight" else (it.load_note or ""),
                    total,
                    f"Belt: {belt}" if belt else "",
                    f"Rest {_mmss(rest)}",
                    it.tempo and f"tempo {it.tempo}",
                    sides_cue,
                    it.notes or "",
                    protocol,
                    how_to,
                ]
                if x
            )
            spec = (
                ("reps_only", *_custom_spec(ex, it, ctx.cfg.tests.tests)[1:]) if inches or calories else None
            )
            split = it.per_side and not alternating
            sides: list[str | None] = list(SIDES) if split else [None]
            superset = None
            if split:  # left and right as two exercises in a superset (Hevy has no per-side sets)
                superset = next_superset
                next_superset += 1
            for side in sides:
                side_title = ex.hevy_name(side, calories=calories)
                entry: dict[str, Any] = {
                    # the library's built-in template is the plain (timed) exercise: calorie logging needs its own
                    "exercise_template_id": (ex.hevy_template_id if side is None and not calories else None)
                    or resolver.resolve(side_title, *(spec or _custom_spec(ex, it, ctx.cfg.tests.tests))),
                    # left side: a short switch; the full rest comes after the right side
                    "rest_seconds": rules.side_switch_s if side == "Left" else rest,
                    # both sides keep every cue (RIR, load, belt, rest, how-to)
                    "notes": f"{side} side. {note}".strip() if side else note,
                    "sets": [dict(st) for st in sets],
                }
                if superset is not None:  # only per-side pairs are supersets; others send no superset_id
                    entry["superset_id"] = superset
                exercises.append(entry)
    if not exercises:
        return None
    return {
        "title": f"{s.date:%a %b %d}: {s.title}",
        "folder_id": folder_id,
        "notes": f"{s.intent} (~{s.expected_minutes} min). Check-in tag in notes: back X shoulder Y knee Z rpe N",
        "exercises": exercises,
    }


def _mmss(sec: float) -> str:
    sec = int(round(sec))
    return f"{sec // 60}:{sec % 60:02d}"


def _pace_target(seg) -> str:
    """Absolute pace from the coach's own zones ('9:46-10:48/mi Pace'), so the watch target doesn't depend on a
    threshold pace being set in Intervals.icu (seen unset live 2026-11-12); % of threshold only as a fallback."""
    if seg.pace_s_per_mi:
        fast, slow = sorted(seg.pace_s_per_mi)
        return f"{_mmss(fast)}-{_mmss(slow)}/mi Pace"
    lo, hi = PACE_FACTORS[seg.zone]
    return f"{round(100 / hi)}-{round(100 / lo)}% Pace"


def intervals_event(s: Session, ctx: Context) -> dict | None:
    segs = s.run_segments()
    if not any(seg.modality == "run" for seg in segs):
        return None
    lines = []
    for seg in segs:
        if seg.modality != "run":
            continue
        size = f"{seg.distance_mi:g}mi" if seg.distance_mi else f"{seg.duration_min:g}m"
        prefix = f"{seg.reps}x\n" if seg.reps > 1 else ""
        rec = f"\n- {seg.recovery_min:g}m 60-70% Pace" if seg.recovery_min and seg.reps > 1 else ""
        lines.append(f"{prefix}- {size} {_pace_target(seg)} {seg.label}{rec}")
    return {
        "category": "WORKOUT",
        "type": "Run",
        "start_date_local": f"{s.date.isoformat()}T{s.start_time}:00",
        "name": s.title,
        "description": "\n".join(lines)
        + "".join(f"\n\n{b.notes}" for b in s.blocks if b.kind == "test" and b.notes)
        + f"\n\n{s.intent}",
        "external_id": f"coach-{s.id}",
        "moving_time": s.expected_minutes * 60,
    }


def _push_sessions(
    sessions: list[Session],
    ctx: Context,
    sources: Sources | None,
    dry_run: bool,
    archive_before: dt.date | None = None,
) -> dict:
    ids = ctx.state.get("push_ids") or {}
    out: dict = {"dry_run": dry_run, "hevy": [], "intervals": []}
    resolver = TemplateResolver(sources.hevy if sources else None, read_only=dry_run)
    folders = FolderResolver(sources.hevy if sources else None, ids, read_only=dry_run)
    events = []
    try:
        if archive_before is not None:
            moved = archive_routines(ids, folders, ctx, sources, archive_before, dry_run)
            if errors := [m for m in moved if "error" in m]:
                out["hevy_archive_errors"] = errors
            if moved := [m for m in moved if "error" not in m]:
                out["hevy_archived"] = moved
        this_week = None
        if any(s.type != "rest" for s in sessions):
            this_week = folders.resolve(FOLDER_THIS_WEEK)
        for s in sessions:
            if s.type == "rest":
                continue
            if s.location in {"gym", "travel", "home"} and s.type not in {
                "run_easy",
                "run_long",
                "run_quality",
                "race",
            }:
                r = hevy_routine(s, ctx, resolver, folder_id=this_week)
                if r:
                    if dry_run or sources is None:
                        out["hevy"].append(
                            {"session": s.id, "routine": r["title"], "exercises": len(r["exercises"])}
                        )
                    else:
                        rid = sources.hevy.upsert_routine(r, ids.get(f"hevy:{s.id}"))
                        ids[f"hevy:{s.id}"] = rid
                        # pushed again (a rescheduled day): it's in the current-week folder now, archive it again later
                        ids.pop(f"hevy-archived:{s.id}", None)
                        out["hevy"].append({"session": s.id, "routine_id": rid})
            e = intervals_event(s, ctx)
            if e:
                events.append(e)
    finally:  # routines already created keep their ids even if a later one fails (a re-push would duplicate them)
        if not dry_run:
            ctx.state.put("push_ids", ids)
    if events:
        if dry_run or sources is None:
            out["intervals"] = [{"session": e["external_id"], "name": e["name"]} for e in events]
        else:
            out["intervals"] = sources.intervals.upsert_events(events)
    if folders.would_create:
        out["hevy_folders_needed"] = folders.would_create
    if resolver.would_create:
        out["hevy_custom_exercises_needed"] = resolver.would_create
    if resolver.created:
        out["hevy_custom_exercises_created"] = resolver.created
    return out


def push_week(plan: WeekPlan, ctx: Context, sources: Sources | None, dry_run: bool | None = None) -> dict:
    violations = validate_week(plan, ctx.validation(plan))
    if violations:
        raise PushRefused(violations)
    if plan.approval == "pending":
        return {"skipped": "plan is pending approval (coach approve <proposal>)"}
    dry = (not ctx.cfg.settings.push.enabled) if dry_run is None else dry_run
    today = ctx.today
    upcoming = [s for s in plan.sessions if s.date >= today]
    # earlier weeks leave the current-week folder; today's routine stays even when pushing next week on Sunday
    return _push_sessions(upcoming, ctx, sources, dry, archive_before=min(plan.start, today))


def push_day(
    session: Session,
    ctx: Context,
    sources: Sources | None,
    plan: WeekPlan | None = None,
    dry_run: bool | None = None,
) -> dict:
    vctx = ctx.validation(plan)
    week_type = plan.week_type if plan else "training"
    violations = validate_session(session, vctx, week_type, plan)
    if violations:
        raise PushRefused(violations)
    dry = (not ctx.cfg.settings.push.enabled) if dry_run is None else dry_run
    monday = session.date - dt.timedelta(days=session.date.weekday())
    return _push_sessions([session], ctx, sources, dry, archive_before=min(monday, ctx.today))


def current_week_only(plan: WeekPlan, today: dt.date) -> bool:
    return plan.start <= today <= plan.end or plan.start == today + dt.timedelta(days=1)


STANDING_PREFIX = "routine-"


def standing_routine(name: str, ctx: Context) -> Session:
    """An item set from training.yaml as an undated session (a standing routine reused, e.g. every evening)."""
    from coach.coaching.skills import design as D

    if name not in ctx.cfg.training.item_sets:
        raise KeyError(f"no item set '{name}' in training.yaml")
    ws = ctx.cfg.training.item_set(name)
    P = D.Picker(ctx, "training", "home")
    block = D.items_block("mobility", ws.items, P, ws.title)
    s = Session(
        id=f"{STANDING_PREFIX}{name}",
        date=ctx.today,
        type="recovery",
        title=ws.title,
        intent="Standing routine: reuse it from Hevy whenever it is prescribed",
        location="home",
        expected_minutes=0,
        blocks=[block],
    )
    s.expected_minutes = D.estimate_minutes(s, ctx.zones.threshold_pace_s_per_mi)
    return s


def push_routine(name: str, ctx: Context, sources: Sources | None, dry_run: bool | None = None) -> dict:
    """Create or update one standing Hevy routine from an item set (same routine id every time). Runs the session
    validator (health gates: a red flag or illness refuses it) plus the library/equipment checks that the validator
    skips for recovery-type sessions."""
    s = standing_routine(name, ctx)
    lib, available = ctx.cfg.library, ctx.cfg.equipment.available("home", ctx.cfg.profile.travel_equipment)
    violations = validate_session(s, ctx.validation(None))
    specs = ctx.cfg.training.item_set(name).items
    if len(s.all_items()) < len(
        specs
    ):  # the picker drops items with no home-doable version: say so, never silently
        kept = {it.exercise_id for it in s.all_items()}
        lost = [sp.exercise or sp.family for sp in specs if (sp.exercise or sp.family) not in kept]
        violations.append(
            Violation("EQUIPMENT", f"not doable at home, would be dropped: {', '.join(map(str, lost))}", s.id)
        )
    for it in s.all_items():
        ex = lib.get(it.exercise_id)
        if ex is None:
            violations.append(Violation("LIBRARY", f"{it.exercise_id} is not in the exercise library", s.id))
        elif missing := [e for e in ex.equipment if e not in available]:
            violations.append(
                Violation("EQUIPMENT", f"{ex.name} needs {missing}, not available at home", s.id)
            )
    if violations:
        raise PushRefused(violations)
    dry = (not ctx.cfg.settings.push.enabled) if dry_run is None else dry_run
    ids = ctx.state.get("push_ids") or {}
    resolver = TemplateResolver(sources.hevy if sources else None, read_only=dry)
    folders = FolderResolver(sources.hevy if sources else None, ids, read_only=dry)
    r = hevy_routine(s, ctx, resolver, folder_id=folders.resolve(FOLDER_STANDING))
    if r is None:
        return {"error": f"item set '{name}' has no exercises"}
    r["title"] = f"{s.title} (coach)"
    r["notes"] = (
        f"Standing routine (~{s.expected_minutes} min): reuse it whenever it is prescribed. The coach updates it in place."
    )
    key = f"hevy:{s.id}"
    out: dict = {"dry_run": dry, "routine": r["title"], "exercises": len(r["exercises"])}
    if not dry and sources is not None:
        out["routine_id"] = ids[key] = sources.hevy.upsert_routine(r, ids.get(key))
        ctx.state.put("push_ids", ids)
    if resolver.would_create:
        out["hevy_custom_exercises_needed"] = resolver.would_create
    if resolver.created:
        out["hevy_custom_exercises_created"] = resolver.created
    return out
