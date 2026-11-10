"""The coach-daily coordinator in deterministic mode.

Live, Claude runs `.claude/skills/coach-daily/SKILL.md` and makes the coaching decisions itself, calling the same
`coach` commands. This module is the same flow with the deterministic fallbacks in Claude's place: it powers
`coach simulate` and `coach daily --fallback` (a safety net if Claude is unavailable). Steps that would normally be
Claude are marked in the DayRecord (generated_by="fallback")."""

import datetime as dt
from dataclasses import dataclass, field

from coach import clock
from coach.coaching import proposals
from coach.coaching.context import Context, build
from coach.coaching.notify import compose
from coach.coaching.skills import adjust_day, assess, learn, plan_block, plan_week, rehab, replan, review
from coach.coaching.skills import design as D
from coach.config import Config, load_config
from coach.engine import macrocycle as macro_engine
from coach.engine import movement as mv
from coach.engine.validator import validate_week
from coach.integrations.base import Sources
from coach.integrations.push import PushRefused, push_day, push_week
from coach.integrations.sync import sync
from coach.models import DayRecord, WeekPlan
from coach.models.plans import Revision
from coach.store import Store


@dataclass
class DayResult:
    record: DayRecord | None
    notification: str
    log: list[str] = field(default_factory=list)


def bootstrap(state: Store, cfg: Config, today: dt.date) -> list[str]:
    """One-time setup (coach init): macrocycle, starting rungs, config lock, notes, intake template."""
    done = []
    if state.macrocycle() is None:
        state.put("macrocycle", macro_engine.generate(cfg.profile, cfg.season, today))
        done.append("macrocycle generated")
    if state.movement_readiness() is None:
        state.put("movement_readiness", mv.initial_state(cfg.progressions, today))
        done.append("movement readiness at conservative starting rungs")
    if state.get("config_lock") is None:
        proposals.record_config_lock(state, cfg, "initial", today)
        done.append("config lock recorded")
    if not state.keys("notes"):
        for line in cfg.profile.notes_seed:
            state.add_note(today, line, "logistics", "setup")
        done.append("notes seeded")
    if not state.exists("intake"):
        state.put("intake", assess.intake_template(today, cfg.profile.intake_questions))
        done.append("intake questionnaire template written (run it with the athlete in chat)")
    return done


def save_plan(ctx: Context, plan: WeekPlan, created_by: str, day: dt.date, auto_approve: bool) -> list[str]:
    """Validate, save, then push now or mark pending per config/coach.yaml (simulation auto-approves)."""
    log = []
    violations = validate_week(plan, ctx.validation(plan))
    rel = Store.ref("week_plans", plan.week_id)
    if violations:
        log.append(
            f"plan {plan.week_id} fails validation after fallback: " + "; ".join(map(str, violations[:4]))
        )
    mode = ctx.cfg.settings.approval.weekly_plan
    plan.approval = "auto" if mode == "auto" else "pending"
    ctx.state.put("week_plans", plan)
    ctx.state.save_report("week_summaries", week_summary_md(ctx, plan), plan.week_id)
    if plan.approval == "pending":
        kind = "baseline_battery" if plan.week_type == "baseline" else "weekly_plan"
        p = proposals.create(
            ctx.state,
            kind,
            created_by,
            f"Week {plan.week_id} plan ({plan.week_type})",
            f"{len([s for s in plan.sessions if s.type not in {'rest'}])} sessions; see {rel} and summary.md",
            plan.rationale,
            day,
            target=rel,
        )
        if auto_approve and not violations:
            proposals.approve(ctx.state, p.id, day, ctx.cfg, note="simulated athlete approval")
            plan.approval = "approved"
            log.append(f"[sim] athlete approved {p.id}")
        else:
            log.append(f"proposal {p.id} waiting for approval")
    if plan.approval != "pending" and not violations:
        try:
            res = push_week(plan, ctx, None)
            log.append(
                f"pushed week {plan.week_id} ({'dry-run' if res.get('dry_run') else 'live'}): "
                f"{len(res.get('hevy', []))} Hevy routines, {len(res.get('intervals', []))} Intervals events"
            )
        except PushRefused as e:
            log.append("push refused: " + "; ".join(map(str, e.violations[:3])))
    return log


def week_summary_md(ctx: Context, plan: WeekPlan) -> str:
    lines = [f"# Week {plan.week_id} ({plan.week_type}) - {plan.start} to {plan.end}", "", plan.rationale, ""]
    for s in plan.sessions:
        lines.append(
            f"- **{s.date:%a}** {s.title} ({s.expected_minutes} min, {s.location}{', key' if s.key else ''}; carbs {s.carb_tier})"
        )
        for b in s.blocks:
            if b.kind in {"strength", "test"}:
                for it in b.items:
                    load = f" @ {it.load_note}" if it.load_note else ""
                    lines.append(
                        f"  - {it.exercise_id}: {it.sets}x{it.reps or ''}{f' @{it.rir:g} RIR' if it.rir is not None else ''}{load}"
                    )
            if b.metcon:
                lines.append(
                    f"  - {b.metcon.name}: {', '.join(m.exercise_id for m in b.metcon.movements) or 'TBD'}"
                )
            for seg in b.run:
                size = f"{seg.distance_mi:g} mi" if seg.distance_mi else f"{seg.duration_min:g} min"
                lines.append(f"  - {seg.label}: {size} {seg.zone}{f' x{seg.reps}' if seg.reps > 1 else ''}")
    if plan.deviations:
        lines += [
            "",
            "**Deviations from the outline:**",
            *[f"- {d.field}: {d.planned} -> {d.actual} ({d.reason})" for d in plan.deviations],
        ]
    return "\n".join(lines) + "\n"


def _transition(
    ctx: Context, today: dt.date, next_start: dt.date, sources: Sources, auto_approve: bool, weather
) -> list[str]:
    """Sunday before a new block: score tests -> block review -> next goal -> (approval) -> plan-block."""
    log: list[str] = []
    macro = ctx.macro
    assert macro is not None
    new_block = macro.block_for(next_start)
    if new_block is None:
        return ["season over: regenerate the macrocycle"]
    if next_start == macro.blocks[0].start:
        bid, phase = f"{macro.season}-B0", "baseline"
        week_start = macro.baseline_start
    else:
        prev = macro.block_for(today)
        assert prev is not None
        bid, phase = prev.id, "end"
        week_start = prev.transition_start
    plan = ctx.state.week_plan(clock.iso_week_id(week_start))
    scheduled = {t: s.date for s in (plan.sessions if plan else []) for t in s.tests}
    ts = assess.score_week(ctx, bid, phase, scheduled, weather, end_day=today)
    ctx.state.put("test_sets", ts)
    log.append(f"assess: scored {len(ts.results)} tests ({', '.join(r.test_id for r in ts.results)})")
    z = assess.update_zones_from(ctx, ts)
    if z:
        from coach.engine.paces import Zones

        ctx.zones = Zones(lthr=z.lthr, threshold_pace_s_per_mi=z.threshold_pace_s_per_mi)
        log.append(f"zones updated: LTHR {z.lthr}, threshold {z.threshold_pace_s_per_mi} s/mi")
    entry = ts.model_copy(deep=True)
    entry.block_id, entry.phase = new_block.id, "start"
    ctx.state.put("test_sets", entry)
    if phase == "end":
        ctx.state.save_report("block_reviews", review.block_review(ctx, bid), bid)
        log.append(f"review: block review written for {bid}")
    # long-term goals: feasibility check every transition; behind -> a timeline proposal (never a silent change)
    for i, check in assess.goal_progress(ctx, today):
        g = ctx.cfg.profile.goals.long_term[i]
        log.append("assess: " + assess.describe_check(g.name, check))
        tp = assess.goal_timeline_proposal(ctx, i, check, today)
        if tp:
            log.append(f"assess: {tp.title} ({tp.id})")
    log += assess.propose_race_targets(ctx, today)
    goal, _ = assess.propose_goal(ctx, new_block, ts)
    prop = assess.save_goal_proposal(ctx, goal, today)
    log.append(
        f"assess: goal proposed ({goal.primary.test_id} {goal.primary.baseline_value} -> {goal.primary.target_value})"
    )
    if auto_approve:
        proposals.approve(ctx.state, prop.id, today, ctx.cfg, note="simulated athlete approval")
        goal.status = "approved"
        log.append(f"[sim] athlete approved block goal {prop.id}")
    outline = plan_block.build_outline(ctx, new_block, goal if goal.status == "approved" else None)
    if goal.status != "approved":
        outline.revisions.append(
            Revision(at=today, reason="goal pending approval", change="provisional outline")
        )
    from coach.engine.validator import validate_outline

    errs = validate_outline(outline)
    ctx.state.put("block_outlines", outline)
    log.append(
        f"plan-block: outline {new_block.id} ({len(outline.weeks)} wk, deloads {outline.deload_weeks}, {outline.calorie_phase})"
        + (f" INVALID: {errs}" if errs else "")
    )
    return log


def run_daily(
    sources: Sources,
    state: Store | None = None,
    today: dt.date | None = None,
    phase: str = "main",
    auto_approve: bool = False,
    cfg: Config | None = None,
) -> DayResult:
    state = state or Store()
    cfg = cfg or load_config()
    today = today or clock.today()
    log: list[str] = []
    if phase == "catchup":
        prior = state.day_record(today)
        if prior is None or prior.status != "waiting_for_recovery":
            return DayResult(None, "", ["catch-up: nothing waiting"])
    log += bootstrap(state, cfg, today)
    report = sync(sources, state, today, cfg)
    extras: dict = {"stale": [s for s in report["stale"] if not s.startswith("whoop: today's")]}
    ctx = build(state, cfg, today)
    if cfg.settings.paused:
        rec = DayRecord(date=today, status="paused", generated_by="fallback", stale_sources=report["stale"])
        rec.notification = compose(rec, extras)
        state.put("day_records", rec)
        return DayResult(rec, rec.notification, log)
    try:
        weather = sources.weather.hourly(today - dt.timedelta(days=1), today + dt.timedelta(days=1))
    except Exception as e:  # noqa: BLE001
        weather = None
        extras["stale"].append(f"weather: {e}")

    # --- make sure this week has a plan (first run / baseline week) ---
    plan = ctx.week_plan(today)
    if plan is None and ctx.macro and (ctx.in_baseline or ctx.outline is not None):
        plan = plan_week.plan_week(ctx, clock.monday_of(today))
        log += save_plan(ctx, plan, "assess" if ctx.in_baseline else "plan-week", today, auto_approve)
        plan = ctx.week_plan(today)

    # --- rehab: yesterday's exposures, pain reports, region flags ---
    form_checks = []
    for ev in rehab.update(ctx, today):
        log.append(f"rehab: {ev}")
        if ev.startswith("FORM CHECK"):
            form_checks.append(ev.removeprefix("FORM CHECK: "))

    # --- missed sessions -> replan (protect key sessions) ---
    if (
        plan
        and today.weekday() >= 2
        and not any(d.reason.endswith("missed sessions this week") for d in plan.deviations)
    ):
        res = replan.missed_sessions(ctx, plan, today)
        if res:
            plan, notes = res
            state.put("week_plans", plan)
            log.append("replan: " + "; ".join(notes))
            extras.setdefault("handoffs", []).append(
                "Replanned the rest of the week around missed sessions (key sessions kept)."
            )

    # --- adjust-day (+ fuel, rehab swaps) ---
    rec = adjust_day.adjust(ctx, today, plan, sources, weather)
    rec.stale_sources = report["stale"]
    if rec.session is not None and rec.status == "complete":
        try:
            rec.pushed = push_day(rec.session, ctx, None, plan)
        except PushRefused as e:
            log.append("push refused for today: " + "; ".join(map(str, e.violations[:3])))
            rec.changes.append(
                adjust_day.Change(what="fell back to Z1 + mobility", why="adjusted session failed validation")
            )
            rec.session = D.recovery_session(ctx, today)
            rec.pushed = push_day(rec.session, ctx, None, plan)
    # --- sustained Red / joint >= 4 -> reactive deload ---
    r = rec.readiness
    if r and r.sustained_red and ctx.outline is not None:
        recent = [p for p in state.proposals() if p.kind == "early_deload" and (today - p.created).days < 10]
        if not recent:
            joint_trigger = any(v >= cfg.profile.thresholds.joint_red for v in r.joints.values())
            deload = replan.reactive_deload(ctx, today, "; ".join(r.reasons))
            if deload:
                new_outline, wk = deload
                rel = Store.ref("block_outlines", new_outline.block_id)
                p = proposals.create(
                    state,
                    "early_deload",
                    "replan",
                    f"Pull deload forward to week {wk}",
                    f"Week {wk} becomes a deload; later deloads re-spaced to {new_outline.deload_weeks}",
                    "; ".join(r.reasons),
                    today,
                    before=ctx.outline.deload_weeks,
                    after=new_outline.deload_weeks,
                    target=rel,
                    payload={"records": {rel: new_outline.model_dump(mode="json")}},
                )
                if joint_trigger or auto_approve:
                    proposals.approve(
                        state,
                        p.id,
                        today,
                        cfg,
                        note="joint >= 4: applied immediately"
                        if joint_trigger
                        else "simulated athlete approval",
                    )
                    ctx.outline = new_outline
                    rec.handoffs.append(
                        f"Reactive deload: next week (block week {wk}) is now a deload. Why: {r.reasons[0]}."
                    )
                else:
                    rec.handoffs.append(f"Proposed: pull the deload forward to next week ({p.id}).")
                log.append(f"replan: reactive deload -> week {wk} ({p.id})")

    # --- Sunday: review this week, plan next week (block transition first if due) ---
    if today.weekday() == 6:
        this_plan = ctx.week_plan(today)
        if this_plan:
            md, summary = review.weekly_review(ctx, this_plan)
            state.save_report("week_reviews", md, this_plan.week_id)
            log.append(f"review: week {this_plan.week_id} adherence {summary['adherence_pct']}%")
            if summary["questions"]:
                extras["weekly"] = "Check-in: " + summary["questions"][0]
        next_start = today + dt.timedelta(days=1)
        ctx = build(state, cfg, today)
        if (
            ctx.macro
            and (ctx.macro.block_for(next_start) is not None)
            and (ctx.macro.block_for(next_start) != ctx.macro.block_for(today))
        ):
            log += _transition(ctx, today, next_start, sources, auto_approve, weather)
            extras["transition"] = "New block starts tomorrow: tests scored, goal proposed" + (
                " and approved." if auto_approve else " - waiting for your OK."
            )
            ctx = build(state, cfg, today)
        nb = ctx.macro.block_for(next_start) if ctx.macro else None
        if nb and state.outline(nb.id):
            nxt = plan_week.plan_week(ctx, next_start)
            nxt, avail = replan.apply_availability(ctx, nxt)
            if avail:
                log.append("replan: availability -> " + "; ".join(avail))
            log += save_plan(ctx, nxt, "plan-week", today, auto_approve)
            if nxt.deviations:
                log.append(
                    "plan-week deviations: " + "; ".join(f"{d.field}: {d.reason}" for d in nxt.deviations)
                )

    # --- first Wednesday: learn ---
    if clock.first_wednesday(today):
        md, prop = learn.calibration(ctx, today)
        state.save_report("science", learn.science_audit_scaffold(ctx, today) + "\n" + md, f"{today:%Y-%m}")
        log.append(
            "learn: monthly calibration + science audit scaffold" + (f"; proposal {prop.id}" if prop else "")
        )
        if prop:
            extras["learn"] = f"Monthly calibration: proposed a 4-week trial ({prop.title})."

    if ctx.macro and ctx.macro.unconfirmed_races and today.weekday() == 6:
        extras["unconfirmed"] = (
            "Note: plan depends on unconfirmed race dates (" + ", ".join(ctx.macro.unconfirmed_races) + ")."
        )
    rec.approvals_pending = proposals.pending_summary(state)
    for fc in form_checks:
        rec.handoffs.append(f"Next rung earned: {fc}.")
    for h in extras.get("handoffs", []):
        rec.handoffs.append(h)
    rec.notification = compose(rec, extras, cfg.settings.notification_detail)
    state.put("day_records", rec)
    return DayResult(rec, rec.notification, log)


def tests_scheduled(plan: WeekPlan) -> dict[str, dt.date]:
    return {t: s.date for s in plan.sessions for t in s.tests}
