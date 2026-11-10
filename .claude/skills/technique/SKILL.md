---
name: technique
description: Skill and form coaching. Runs the Olympic-lift and gymnastics progressions, reviews form from photo/video frames the athlete shares, coaches running form from Running Dynamics Pod trends (cadence, ground contact time and balance, vertical oscillation), gives 1-2 cues and drills, and decides when a skill is competent enough to appear in metcons.
---

# technique

**When:** form-check requests (frames shared in chat), every 3-4 weeks (ask the athlete to film a key lift or skill),
skill milestones reported in chat ("15 unbroken kipping pull-ups"), running-form reviews.

**Context:** `config/skills.yaml`, `state/movement_readiness.json` (gates), run sessions in `state/metrics/`
(cadence, GCT, balance, vertical oscillation), `state/notes.md`.

## Procedure
- **Skills:** move a skill's `current_level` one step at a time when the athlete demonstrates the next level's
  criterion; mark competent only if the gating rung allows it. Competent skills may appear in metcons; until then
  they're practised fresh (10-12 min, 1-3 reps, <= 70%).
- **Form checks:** describe what you see in still frames, give **1-2 cues and one drill**, say what you can't judge
  from stills. An in-person coach session is optional.
- **Running form:** cadence target 170-180 spm; flag GCT balance drifting > 1.5% from 50/50, high vertical
  oscillation, long ground contact; prescribe one drill.
- Log cues and level changes in `state/notes.md` (e.g. "form check requested 2026-12-20").

## Writes
`config/skills.yaml` (levels), `state/notes.md` (cues).

## Never
- Put an unmastered skill in a metcon; diagnose injuries from video; give more than two cues at once.
