---
name: technique
description: Skill and form coaching. Runs the Olympic-lift and gymnastics progressions, reviews form from photo/video frames the athlete shares, coaches running form from Running Dynamics Pod trends (cadence, ground contact time and balance, vertical oscillation), gives 1-2 cues and drills, and decides when a skill is competent enough to appear in metcons.
---

# technique

**When:** form-check requests (frames shared in chat), every 3-4 weeks (ask the athlete to film a key lift or skill),
skill milestones reported in chat ("15 unbroken kipping pull-ups"), running-form reviews.

**Context:** `athlete/config/skills.yaml`, `movement_readiness` (gates), run sessions (`coach report mileage`, `coach context --week`)
(cadence, GCT, balance, vertical oscillation), `athlete/data/notes.md`.

## Procedure
- **Skills:** move a skill's `current_level` one step at a time when the athlete demonstrates the next level's
  criterion; mark competent only if the gating rung allows it. Competent skills may appear in metcons; until then
  they're practised fresh (10-12 min, 1-3 reps, <= 70%).
- **Form checks:** describe what you see in still frames, give **1-2 cues and one drill**, say what you can't judge
  from stills. An in-person coach session is optional.
- **Running form:** raise cadence ~5-10% from the athlete's own baseline (reduces joint loading; the evidence that it
  prevents injury is weaker), drifting toward 170-180 spm rather than forcing a fixed number; flag GCT balance drifting > 1.5% from 50/50, high vertical
  oscillation, long ground contact; prescribe one drill.
- Log cues and level changes as `notes` (category `skill`, e.g. "form check requested"); record a cleared form check with `coach form-check <family> --by coach|physio`.

## Writes
`athlete/config/skills.yaml` (levels), `notes` (cues), `movement_readiness` (via `coach form-check`).

## Never
- Put an unmastered skill in a metcon; diagnose injuries from video; give more than two cues at once.
