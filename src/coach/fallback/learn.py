"""learn fallback: monthly calibration (do my rules fit this athlete?) + science-audit scaffold.

The science audit needs live retrieval (PubMed E-utilities / web search) and Claude; offline it only writes the
scaffold and says so. It never invents citations."""

import datetime as dt
import statistics

from coach import proposals
from coach.context import Context


def calibration(ctx: Context, day: dt.date, weeks: int = 8) -> tuple[str, object | None]:
    start = day - dt.timedelta(weeks=weeks)
    by_state: dict[str, list[float]] = {"green": [], "yellow": [], "red": []}
    for i in range((day - start).days):
        d = start + dt.timedelta(days=i)
        rec = ctx.state.day_record(d)
        ci = next(iter(ctx.state.checkins(d + dt.timedelta(days=1), d + dt.timedelta(days=1))), None)
        if rec and rec.readiness and rec.readiness.state in by_state and ci and ci.session_rpe:
            by_state[rec.readiness.state].append(ci.session_rpe)
    g, y = by_state["green"], by_state["yellow"]
    lines = [
        f"## Calibration {day:%Y-%m}",
        "",
        f"Window: {start} -> {day}. Next-day session RPE by readiness state:",
    ]
    for k, v in by_state.items():
        lines.append(f"- {k}: n={len(v)}, mean RPE {statistics.fmean(v):.2f}" if v else f"- {k}: n=0")
    prop = None
    th = ctx.cfg.profile.thresholds
    if len(g) >= 8 and len(y) >= 3:
        diff = statistics.fmean(y) - statistics.fmean(g)
        if diff < 0.3:
            new = th.recovery_green_min - 3
            lines.append(
                f"\nYellow days barely differed from Green (+{diff:.2f} RPE). Hypothesis: the Green cut-off ({th.recovery_green_min}) is "
                f"too strict for this athlete. Proposed N=1 trial: Green from {new} for 4 weeks."
            )
            prop = proposals.create(
                ctx.state,
                "calibration",
                "learn",
                f"Trial: Green recovery cut-off {th.recovery_green_min} -> {new}",
                f"4-week N=1 trial. Metric: next-day session RPE and completion on 'new Green' days. Stop rule: revert if RPE on those days "
                f">= Yellow-day mean + 0.5 or any joint flag.",
                f"Yellow days predicted RPE only +{diff:.2f} vs Green over {weeks} weeks (n={len(y)}).",
                day,
                before={"recovery_green_min": th.recovery_green_min},
                after={"recovery_green_min": new},
                payload={
                    "config_patch": {
                        "file": "athlete_context.json",
                        "path": ["thresholds", "recovery_green_min"],
                        "value": new,
                    }
                },
                target_path="config/athlete_context.json#thresholds.recovery_green_min",
            )
        else:
            lines.append(
                f"\nYellow days ran +{diff:.2f} RPE vs Green: the readiness rules are discriminating. No change proposed."
            )
    else:
        lines.append(
            "\nNot enough paired data yet for a calibration call (need >= 8 Green and >= 3 Yellow days with next-day RPE)."
        )
    return "\n".join(lines) + "\n", prop


def science_audit_scaffold(ctx: Context, day: dt.date, live: bool = False) -> str:
    block = ctx.block.name if ctx.block else "baseline"
    return (
        "\n".join(
            [
                f"# Science audit {day:%Y-%m}",
                "",
                f"Focus: current block ({block}) and open questions in notes.md.",
                "",
                "Status: "
                + (
                    "pending Claude search (PubMed E-utilities + web)."
                    if live
                    else "NOT RUN - offline/mock mode has no literature access. No findings, no citations."
                ),
                "",
                "Rules: a finding earns a proposal only if it comes from a meta-analysis, systematic review or multiple RCTs in trained humans, "
                "its benefit outweighs the added complexity, and it is framed as a 4-week N=1 trial (hypothesis, metric, stop rule). "
                "Every citation must carry a PMID/DOI actually retrieved in this run.",
            ]
        )
        + "\n"
    )
