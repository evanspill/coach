# Safety rules (shared by `log`, `adjust-day`, `replan`, `rehab`)

The coach is not a medical provider. These rules are stated plainly and never trained through.

## Red flags -> stop training and see a doctor
- Chest pain, pressure or tightness
- Palpitations or an irregular / racing heartbeat at rest or out of proportion to effort
- Fainting, near-fainting or blacking out
- Unusual breathlessness (out of proportion to effort)
- Numbness, tingling, or pain radiating down a limb
- Sharp or worsening joint pain
- Signs of rhabdomyolysis: dark (cola-coloured) urine after a hard session
- Signs of heat illness: confusion, disorientation, stopped sweating, collapse (cool down immediately, call for help)

If any appears: **stop**, get checked by a doctor (call 911 for chest pain, fainting or severe breathlessness).
`log` records it in `athlete/data/health.json` (`red_flags`), every plan with training on or after that date fails
`coach validate` (`RED_FLAG`) and adjust-day replaces sessions with rest, until the athlete reports a doctor's
clearance (`cleared_on`).

## Illness: the neck check
- Symptoms **only above the neck** (runny/stuffy nose, sneezing, mild sore throat): easy movement only
  (walk, mobility, easy Zone 2). Nothing hard.
- **Any symptoms below the neck** (fever, chills, chest congestion, body aches, GI illness): **no training** until
  they resolve and you've been fever-free for at least 24 h without medication. Then a graded return: day 1 Z1 only,
  day 2 easy Z2, day 3+ deload volume, then normal.

## In-session pain rule
- Discomfort > 2/10 during a movement: regress range of motion or switch to an isometric next time; the family
  drops one rung.
- Next-morning stiffness rises: that movement's load drops ~15% and uses a 3 s eccentric for 2 weeks.
- A region rated >= 3 on 2 consecutive check-ins restricts that region's exercise tags (swapped via regressions)
  and drops its families one rung for a week. Any joint rated >= 4 is Red and pulls a deload forward.

## Other limits
- No true 1RMs: tests are rep-maxes at RPE 9.
- Unmastered Olympic/gymnastics skills never go in metcons or after fatiguing work.
- Bloodwork: trends are flagged with "discuss with your physician"; the coach never diagnoses or changes doses.
- A physical therapist assessment is recommended before Block 1 (back + shoulder) and again if a family
  regresses twice in 4 weeks.
