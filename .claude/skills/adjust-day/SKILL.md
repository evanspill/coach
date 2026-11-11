---
name: adjust-day
description: Daily autoregulation. Applies readiness (Whoop recovery, HRV trend, RHR, joints), joint flags, weather and same-day bar speed to today's session, and sets today's recovery prescription (recovery tools, mobility) and fuelling (via fuel). Small changes only; anything bigger hands off to replan. Runs every morning.
---

# adjust-day

**When:** every daily run; in chat for "swap today's X".

**Context:** `coach readiness` (state + reasons + joint flags), `coach status`, today's planned session in
today's planned session (`coach record get week_plans --key <iso-week>`), yesterday's day record, `health_events` (`coach record list health_events`), weather (the daily run's sync), check-ins.

## Rules (thresholds come from config; the most restrictive state wins)
- **Green:** run the plan as written.
- **Yellow:** keep primary strength; replace metcon/threshold work with **40 min Zone 2**.
- **Red:** today and the next 48 h are **Z1 + mobility**; accessory volume -50% for the following days;
  consider a reactive deload (sustained Red or a joint >= 4 -> hand off to `replan`).
- **Test day:** needs Green or Yellow; on Red move the test within +/-2 days (strength, run TT and engine stay on
  separate days) - via `replan` if it reshapes the week.
- **Joint flags** (region >= 3 on two consecutive check-ins): swap restricted exercises using regressions (`rehab`).
- **Weather** (temp F + dew point F): < 130 normal; 130-150 slow 15-30 s/mi + sodium; > 150, icy (<= 0 C with
  precipitation in the prior 12 h) or outside daylight -> quality/long work moves to the gym treadmill (or erg).
- **Bar speed (optional VBT):** top warm-up set >= 10% slower than usual -> cap the load even on Green; noticeably
  faster -> small increase.
- **Safety first:** red flag -> stop (rest, see a doctor); illness neck check (`docs/SAFETY.md`). Safety downgrades
  apply immediately; other session-type swaps follow `approval.manual_if` in `athlete/config/coach.yaml`.
- **Recovery prescription:** after high-strain days (day strain above `high_strain`, threshold, long runs, Hyrox) -> the athlete's recovery
  prescriptions in `athlete_context.json` `recovery` (post-session tool, evening mobility targeted at the loaded areas,
  nightly routine).
- Call `fuel` for today's macros and the peri-workout cue; `rehab` for gated movements.

## Writes
`day_records` (`DayRecord`: readiness, weather call, adjusted session, changes with reasons, recovery, nutrition, gear
alerts, pushed result) via `coach record add day_records --file /tmp/day.json` (fills loads/paces and validates the
session), then `coach push --day`.

## Hand off to `replan` when
2+ missed sessions this week, sustained Red, illness, travel, or the change spans more than today.

## Never
- Make big plan changes here, train through a red flag or a below-the-neck illness, or invent loads/paces.
