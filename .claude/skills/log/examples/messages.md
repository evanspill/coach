# Chat messages -> records (`coach log "<message>"`)

| Athlete says | Record written | Reply |
|---|---|---|
| "check in: back 2, shoulder 3, slept badly" | `checkins/<date>.json`: `{"joints": {"back": 2, "shoulders": 3}, "sleep_note": "slept badly", "source": "chat"}` | "Check-in logged: back 2, shoulders 3" |
| "Finished the Hyrox sim: 4 rounds in 26:40, sled heavy on round 3, wall balls unbroken, RPE 8.5" | `metcons/<date>.json`: kind `hyrox_sim`, `time_s` 1600, `rounds` 4, `rpe` 8.5, movement notes (sled heavy r3, wall balls unbroken) | "Logged hyrox_sim: time_s=1600, rounds=4, rpe=8.5" |
| "did the metcon - 4 rds + 12, wallballs unbroken, burpees slow, rpe 8" | `metcons/<date>.json`: rounds 4 + 12 reps, rpe 8 | "Logged metcon: rounds=4, extra_reps=12, rpe=8.0" |
| "metcon done, legs were toast" | `metcons/<date>.json` (score missing) | follow-up: "What was the final score (time, or rounds + reps)?" |
| "Shoulder hurt during pressing, about 3/10" | `checkins/<date>.json`: `session_pain: {"press": 3}` | pain rule explained; "How does it feel at rest right now?" |
| "Felt some chest pain and got dizzy on the treadmill" | `health.json` red flag `chest pain` | "Stop training now and get checked by a doctor today ... call 911 ..." - all sessions stop |
| "Woke up with a fever and body aches" | `health.json` illness `below_neck` | "no training until they're gone, then a graded return" -> `replan` |
| "dips aggravate my right shoulder" | `notes.md`: durable fact | - |
| "got 10 unbroken toes to bar" | `skills.yaml` level +1 (competent if the kipping rung allows) via `technique` | - |
