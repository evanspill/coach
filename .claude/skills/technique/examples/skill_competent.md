# Skill marked competent (scenario `technique: skill marked competent`)

Athlete: "Skill session today: got 10 unbroken toes to bar, felt smooth"

- `coach log` detects the milestone -> `technique` checks the gate (`kipping` rung 3 required for toes-to-bar).
- `athlete/config/skills.yaml`: `toes_to_bar.current_level` 2 -> 3 (= `competent_level`).
- `athlete/data/notes.md`: "- 2027-02-01: Toes-to-bar -> level 3 (10+ linked T2B) - COMPETENT: allowed in metcons."
- From now on `design-session` may put toes-to-bar inside metcons; before that it scaled to hanging knee raises.

If the kipping rung were below 3, the level would be held: "toes_to_bar: held at level 2 (kipping rung 0 < 3)".

Form-check reply shape: what I see (2-3 observations) -> 1-2 cues -> one drill -> what I can't judge from stills.
