"""Builds sessions from the templates in config/training.yaml. The engine supplies only the structure-dependent
generators (run sizing, long run, metcon selection, skill practice, test blocks); all content comes from config."""

import datetime as dt
import math

from coach.coaching.context import Context
from coach.coaching.skills import design as D
from coach.models import Metcon, RunSegment, Session, SessionBlock
from coach.models.season import BlockSpec, BlockTemplate, SessionTemplate


def deload_scaler(ctx: Context, week_type: str, enabled: bool = True):
    factor = ctx.cfg.season.season.deload.volume_factor

    def scale(n: int) -> int:
        if enabled and week_type in D.DELOAD_LIKE:
            return max(1, math.floor(n * factor + 0.5))
        return n

    return scale


def _route(tpl: SessionTemplate, week_number: int) -> str | None:
    if isinstance(tpl.route, dict) and "rotate" in tpl.route:
        routes = tpl.route["rotate"]
        return routes[week_number % len(routes)] if routes else None
    return tpl.route


def _location_for(tpl: SessionTemplate, b: BlockTemplate) -> str:
    return b.location or tpl.location


def _easy(b: BlockTemplate, tpl: SessionTemplate, miles: float, ctx: Context) -> SessionBlock | None:
    miles = max(miles, b.min_miles)
    if miles < 0.5:
        return None
    return D.run_block(b.label or "Easy run", miles, b.zone, _location_for(tpl, b), strides=b.strides)


def _threshold(b: BlockTemplate, tpl: SessionTemplate, miles: float, ctx: Context) -> SessionBlock:
    pace = ctx.zones.threshold_pace_s_per_mi
    rep_mi = round((b.rep_min or 5) * 60 / pace, 2)
    reps = max(2, min(5, int(miles * (b.share_of_miles or 0.55) / rep_mi)))
    easy = max(0.5, round(miles - reps * rep_mi, 1))
    terrain = "treadmill" if _location_for(tpl, b) == "gym" else "flat"
    return SessionBlock(
        kind="run",
        title=b.title or "Threshold intervals",
        run=[
            RunSegment(label="Easy", zone="Z2", distance_mi=easy, terrain=terrain),
            RunSegment(
                label=f"Threshold reps ({b.rep_min or 5:g} min)",
                zone="T",
                distance_mi=rep_mi,
                reps=reps,
                recovery_min=b.recovery_min,
                terrain=terrain,
            ),
        ],
    )


def _track(b: BlockTemplate, tpl: SessionTemplate, miles: float, ctx: Context) -> SessionBlock:
    pace = ctx.zones.threshold_pace_s_per_mi
    rep_min = b.rep_min or 6
    rep_mi = round(rep_min * 60 / pace, 2)
    reps = max(2, min(5, int(miles * 0.45 / rep_mi)))
    cool = 0.8
    warm = max(1.0, round(miles - reps * rep_mi - cool, 1))
    return SessionBlock(
        kind="run",
        title=b.title or "Threshold session",
        run=[
            RunSegment(label="Warm-up miles", zone="Z2", distance_mi=warm),
            RunSegment(
                label=f"Threshold reps ({rep_min:g} min)",
                zone="T",
                distance_mi=rep_mi,
                reps=reps,
                recovery_min=b.recovery_min,
            ),
            RunSegment(label="Cool-down jog", zone="Z1", distance_mi=cool),
        ],
    )


def _long(
    b: BlockTemplate, tpl: SessionTemplate, miles: float, ctx: Context, spec: BlockSpec | None, week_type: str
) -> list[SessionBlock]:
    lr = spec.long_run if spec else None
    mp = lr.mp_finish_min if lr and week_type == "training" else 0
    mp_pace = sum(ctx.zones.pace("MP")) / 2
    blocks = [
        D.run_block(
            "Long run",
            miles,
            mp_finish_min=mp,
            mp_pace_s_per_mi=mp_pace,
            mp_from_miles=lr.mp_finish_from_miles if lr else 8,
        )
    ]
    if lr and lr.erg_extension and week_type == "training":
        run_min = miles * ctx.zones.pace("Z2")[1] / 60
        if run_min < lr.target_minutes - 10:
            extra = int(min(35, lr.target_minutes - run_min))
            blocks.append(
                SessionBlock(
                    kind="run",
                    title="Erg extension (aerobic volume without impact)",
                    run=[
                        RunSegment(
                            label="Z2 bike (gym, after the run)",
                            zone="Z2",
                            duration_min=extra,
                            modality="bike",
                        )
                    ],
                )
            )
    return blocks


def _fixed(b: BlockTemplate) -> SessionBlock:
    segs = [
        RunSegment(
            label=s.label,
            zone=s.zone,
            duration_min=s.duration_min,
            distance_mi=s.distance_mi,
            reps=s.reps,
            recovery_min=s.recovery_min,
            modality=s.modality,
        )
        for s in b.segments
    ]
    return SessionBlock(kind=b.kind, title=b.title or (segs[0].label if segs else ""), run=segs)


def _placeholder(b: BlockTemplate) -> SessionBlock:
    mc = Metcon(
        name=b.name or "Event workout",
        format=b.format or "for_time",
        time_cap_min=b.minutes or 15,
        movements=[],
        stimulus=b.stimulus or "As released",
        scaling=b.scaling or "",
        score_type="rounds_reps",
    )
    return SessionBlock(kind="conditioning", title=b.title or mc.name, metcon=mc)


def build_session(
    ctx: Context,
    role: str,
    day: dt.date,
    week_type: str,
    miles: float,
    week_number: int,
    spec: BlockSpec | None = None,
    tests_today: list[str] | None = None,
) -> Session:
    tpl = ctx.cfg.training.sessions[role]
    if tpl.special == "rest":
        return D.rest_session(ctx, day, tpl.intent)
    if tpl.special == "tests":
        return test_session(ctx, day, tests_today or [], week_type)
    P = D.Picker(ctx, week_type, tpl.location)
    scale = deload_scaler(ctx, week_type, tpl.scale)
    blocks: list[SessionBlock | None] = [D.warmup(tpl.warmup, P) if tpl.warmup else None]
    for b in tpl.blocks:
        if b.generate is None:
            if b.use:
                blk = D.item_set_block(
                    b.kind, b.use, P, scale if b.kind in {"strength", "hypertrophy"} else None
                )
                if b.title:
                    blk.title = b.title
            else:
                blk = D.items_block(
                    b.kind, b.items, P, b.title, scale if b.kind in {"strength", "hypertrophy"} else None
                )
            blocks.append(blk if (blk.items or blk.run) else None)
        elif b.generate == "skill_practice":
            blocks.append(D.skill_block(P, week_number))
        elif b.generate == "metcon":
            blocks.append(D.metcon_block(P, b.pool or "short", b.minutes or 10, week_number, b.name))
        elif b.generate == "placeholder_metcon":
            blocks.append(_placeholder(b))
        elif b.generate == "easy":
            blocks.append(_easy(b, tpl, miles, ctx))
        elif b.generate == "threshold":
            blocks.append(_threshold(b, tpl, miles, ctx))
        elif b.generate == "track_intervals":
            blocks.append(_track(b, tpl, miles, ctx))
        elif b.generate == "long":
            blocks.extend(_long(b, tpl, miles, ctx, spec, week_type))
        elif b.generate == "fixed":
            blocks.append(_fixed(b))
        else:
            raise ValueError(f"session template {role}: unknown generator '{b.generate}'")
    if tpl.cooldown:
        blocks.append(D.cooldown(P, tpl.cooldown))
    return D.make_session(
        ctx,
        day,
        role.replace("_", "-"),
        tpl.type,
        tpl.title,
        tpl.intent,
        blocks,
        location=tpl.location,
        route=_route(tpl, week_number),
        key=tpl.key,
    )


def test_block(ctx: Context, test_id: str, P: D.Picker) -> SessionBlock:
    t = ctx.cfg.tests.tests[test_id]
    sess = t.session
    items = []
    run: list[RunSegment] = []
    if sess.get("family"):
        ex = P.main_lift(sess["family"])
    elif sess.get("exercise"):
        ex = P.pick(sess["exercise"], block_kind="test")
    else:
        ex = None
    if ex:
        items = D._items(
            D.rx(
                ex,
                sess.get("sets", 1),
                sess.get("reps"),
                sess.get("rir"),
                distance_m=sess.get("distance_m"),
                duration_s=sess.get("duration_s"),
                rest_s=sess.get("rest_s"),
                notes=sess.get("notes"),
            )
        )
    for seg in sess.get("run", []):
        run.append(RunSegment(**seg))
    return SessionBlock(
        kind="test",
        title=t.name,
        test_id=test_id,
        items=items,
        run=run,
        notes=t.protocol.get("procedure", ""),
    )


def test_session(ctx: Context, day: dt.date, tests: list[str], week_type: str) -> Session:
    battery = ctx.cfg.tests
    slots = {battery.tests[t].slot for t in tests}
    is_run = "run" in slots
    td = ctx.cfg.training.tests_day
    location = td.run_location if is_run else "gym"
    P = D.Picker(ctx, week_type, location)
    warm = (
        "run"
        if is_run
        else "lower"
        if slots & {"power", "strength_lower"}
        else "upper"
        if "strength_upper" in slots
        else "full"
    )
    order = {"power": 0, "strength_lower": 1, "strength_upper": 1, "run": 2, "engine": 2, "body": 3}
    blocks: list[SessionBlock | None] = [D.warmup(warm, P)]
    blocks += [
        test_block(ctx, t, P) for t in sorted(tests, key=lambda t: order.get(battery.tests[t].slot, 2))
    ]
    cd = D.cooldown(P)
    if is_run:
        cd.run = [RunSegment(label="Cool-down jog", zone="Z1", duration_min=10)]
    blocks.append(cd)
    names = ", ".join(battery.tests[t].name for t in tests) or "tests"
    tpl = ctx.cfg.training.sessions.get("tests")
    return D.make_session(
        ctx,
        day,
        "test",
        "test",
        f"Test day: {names}",
        tpl.intent if tpl else "Tests",
        blocks,
        location=location,
        route=td.run_route if is_run else None,
        key=True,
        tests=tests,
    )
