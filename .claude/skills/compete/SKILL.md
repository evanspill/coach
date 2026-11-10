---
name: compete
description: Event preparation. Taper design and race-day plan (pacing, fuelling, warm-up, gear check, contingencies) for the marathon and Hyrox, CrossFit Open week-by-week strategy (when to attempt, pacing, recovery between attempts, re-attempt decisions), and the post-event review. Use in competition weeks from the outline and for "plan my race".
---

# compete

**When:** competition/taper weeks in the outline (it leads the daily run on those days), "plan my race", Open
workout releases (Thursday nights), after an event (post-event review).

**Context:** `coach context --block`, `zones` (threshold pace, LTHR), `athlete/config/athlete_context.json`
(races, goal times), `athlete/config/skills.yaml` (competent skills -> Rx vs scaled), weather forecast, `event_plans`, `event_results`.

## Procedure
- **Marathon:** 3-week taper (~80 / 60 / 40% volume, intensity kept), race plan with goal pace (from the goal time in
  `athlete_context.json`) checked against current threshold pace, pacing by segment, fuelling (60-90 g carbs/h using glucose + fructose
  products, practised in long runs; sodium),
  warm-up, gear check (`race_gear_checklist`), contingencies (heat tiers, GI, calf twinge). Write
  the `event_plans` report (`coach record add event_plans --key <event> --file plan.md`) and open a `race_plan`
  proposal; it is a proposal until approved.
- **Open week:** attempt Friday after Thursday's release; plan where to break before you need to; Rx only if every
  movement is competent and within rungs, otherwise scaled; shoulder rules apply; re-attempt only with a clear
  pacing gain and Green readiness. Fill the competition session's movements once released (validate it).
- **Hyrox:** pacing for runs vs stations, transitions, fuelling, the fixed simulation as the rehearsal.
- **Post-event:** record the result in `event_results` (`coach record add event_results '{...}'`) and append the review to the event plan within 3 days.

## Writes
`event_plans`, `event_results`, adjusted week plans (validated), proposals (`race_plan`).

## Never
- Add new training stress in race week, or enter an Rx division with unmastered skills.
