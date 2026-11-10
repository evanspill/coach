---
name: replan
description: Disruption handling. Rebuilds the rest of the week, or the block, when life happens - illness (neck check + graded return), travel with no gym, missed sessions, schedule changes, a reactive deload. Protects the week's key sessions first. Use for "I'm sick", "traveling Thu-Sun", 2+ missed sessions, or sustained Red.
---

# replan

**When:** "I'm sick", "traveling Thu-Sun", "the gym is closed Friday", 2+ missed sessions this week, sustained Red
or a joint >= 4 (reactive deload), test-day Red that can't be moved within the week.

**Context:** `coach status`, `coach context --week`, `athlete/data/weeks/<iso>/plan.json`, `athlete/data/blocks/<id>/outline.json`,
`health_events` (`coach record list health_events`), `docs/SAFETY.md`.

## Procedure
- **Illness:** below the neck -> rest days until resolved, then graded return (day 1 Z1, day 2 easy Z2, day 3+
  deload volume, then normal). Above the neck -> easy movement only. Record it in `health_events` (via `log`; `coach health resolve <id>` when it's over).
- **Travel:** move key gym sessions to home days where spacing allows; travel days get bodyweight/band sessions and
  runs where the athlete is (`location: travel`, equipment from `travel_equipment`).
- **Missed sessions:** keep the remaining key sessions (main lift, long run, the key glycolytic session), trim
  accessories, never "make up" by doubling.
- **Reactive deload:** pull the next deload forward to next week, re-space the rest of the block (no 5-week span
  without a deload), add a `revisions` entry to the outline. Needs the athlete's confirmation unless a joint is rated >= 4.
- Every change carries a reason in `deviations` (week) or `revisions` (outline). Validate before saving.

## Writes
Revised `athlete/data/weeks/<iso>/plan.json` and/or `athlete/data/blocks/<id>/outline.json`; proposals (`replan`,
`early_deload`) when approval is needed.

## May call
`design-session`, `plan-week` (rebuild a week), `compete` (event weeks), `log` (health records).

## Never
- Train through illness or a red flag; compress missed work into double days; drop the deload rules.
