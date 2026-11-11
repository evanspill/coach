---
name: compete
description: Event preparation. Taper design and race-day plan (pacing, fuelling, warm-up, gear check, contingencies) for the marathon and Hyrox, CrossFit Open week-by-week strategy (when to attempt, pacing, recovery between attempts, re-attempt decisions), and the post-event review. Use in competition weeks from the outline and for "plan my race".
---

# compete

**When:** competition/taper weeks in the outline (it leads the daily run on those days), "plan my race", Open
workout releases (Thursday nights), after an event (post-event review).

**Context:** `coach context --block`, `zones` (threshold pace, LTHR), `athlete/config/athlete_context.json`
(races), `race_targets` (approved race targets), `coach goals` (long-term goals), `athlete/config/skills.yaml` (competent skills -> Rx vs scaled), weather forecast, `event_plans`, `event_results`.

## Procedure
- **Marathon:** 3-week taper (~80 / 60 / 40% volume, intensity kept), race plan paced from **current fitness**
  (`compete.race_pacing`: threshold pace -> Riegel prediction). An approved race target is used only if fitness
  supports it within the run test's typical error; a long-term goal (e.g. a Boston qualifier) is shown but never
  paced. Pacing by segment, fuelling (60-90 g carbs/h using glucose + fructose
  products, practised in long runs; sodium),
  warm-up, gear check (`race_gear_checklist`), contingencies (heat tiers, GI, calf twinge). Write
  the `event_plans` report (`coach record add event_plans --key <event> --file plan.md`) and open a `race_plan`
  proposal; it is a proposal until approved.
- **Open week:** attempt Friday after Thursday's release; plan where to break before you need to; Rx only if every
  movement is competent and within rungs, otherwise scaled; shoulder rules apply; re-attempt only with a clear
  pacing gain and Green readiness. Fill the competition session's movements once released (validate it).
- **Hyrox:** pacing for runs vs stations, transitions, fuelling, the fixed simulation as the rehearsal.
- **Post-event:** record the result in `event_results` (`coach record add event_results '{...}'`) with `division`,
  `age_group`, `place_in_age_group` and, for the Open, the worldwide `top_pct` from the leaderboard; these feed the
  long-term goal checks (`coach goals --check`). Append the review to the event plan within 3 days.
- **HYROX goal:** sub-1:05 in the Open division; only Open-division results count toward it (Pro uses heavier
  stations, so its times aren't comparable). Record the division with every HYROX result.

## Writes
`event_plans`, `event_results`, adjusted week plans (validated), proposals (`race_plan`).

## Never
- Pace a race from a goal time that current fitness doesn't support, or from a long-term goal.
- Add new training stress in race week, or enter an Rx division with unmastered skills.
