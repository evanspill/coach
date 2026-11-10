---
name: compete
description: Event preparation. Taper design and race-day plan (pacing, fuelling, warm-up, gear check, contingencies) for the marathon and Hyrox, CrossFit Open week-by-week strategy (when to attempt, pacing, recovery between attempts, re-attempt decisions), and the post-event review. Use in competition weeks from the outline and for "plan my race".
---

# compete

**When:** competition/taper weeks in the outline (it leads the daily run on those days), "plan my race", Open
workout releases (Thursday nights), after an event (post-event review).

**Context:** `coach context --block`, `state/zones.json` (threshold pace, LTHR), `config/athlete_context.json`
(races, goal times), `config/skills.yaml` (competent skills -> Rx vs scaled), weather forecast, `state/events/`.

## Procedure
- **Marathon:** 3-week taper (~80 / 60 / 40% volume, intensity kept), race plan with goal pace (sub-3:16 =
  ~7:28-7:29/mi) checked against current threshold pace, pacing by segment, fuelling (60-90 g carbs/h, sodium),
  warm-up, gear check (shoes < 250 mi, pod, gels), contingencies (heat tiers, GI, calf twinge). Write
  `state/events/<event>.md`; it is a proposal until approved.
- **Open week:** attempt Friday after Thursday's release; plan where to break before you need to; Rx only if every
  movement is competent and within rungs, otherwise scaled; shoulder rules apply; re-attempt only with a clear
  pacing gain and Green readiness. Fill the competition session's movements once released (validate it).
- **Hyrox:** pacing for runs vs stations, transitions, fuelling, the fixed simulation as the rehearsal.
- **Post-event review** appended to `state/events/<event>.md` within 3 days.

## Writes
`state/events/<event>.md`, adjusted week plans (validated), proposals (`race_plan`).

## Never
- Add new training stress in race week, or enter an Rx division with unmastered skills.
