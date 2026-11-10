---
name: learn
description: Getting better as a coach. Monthly (first Wednesday) - (1) an external science audit of high-quality recent literature focused on the current block and open questions, and (2) an internal calibration that checks whether the coach's rules fit this athlete (do Yellow days predict worse sessions? is progression too fast? are carb tiers right?). Proposes threshold or rule changes as 4-week N=1 trials; everything needs approval and a changelog entry.
---

# learn

**When:** first Wednesday of each month (kept off Sundays); when the athlete asks "is there anything new on X?".

**Context:** `state/days/` (readiness states), check-ins (next-day session RPE, enjoyment), `coach report ...`,
`docs/TRAINING_ARCHITECTURE.md`, `state/science/` (previous audits, running trials), `state/proposals/`.

## Science audit
- Search PubMed E-utilities (`eutils.ncbi.nlm.nih.gov`) and the web across high-signal sources (ISSN position
  stands, *Sports Medicine*, *JSCR*, research reviews), focused on the current block and open questions in notes.
- **A finding earns a proposal only if:** it is a meta-analysis, systematic review or multiple RCTs in trained humans;
  its benefit outweighs the added complexity; and it is framed as a **4-week N=1 trial** with a hypothesis, metric and
  stop rule.
- Every cited paper must include a real PMID/DOI that this run actually retrieved. Single studies, mouse studies or
  hype never change programming.
- Write `state/science/YYYY-MM.md`.

## Calibration
- Start with `coach` output from the deterministic calibration (it compares next-day RPE on Green vs Yellow days);
  extend it (progression rate vs RPE drift, carb tiers vs session quality, sleep vs readiness).
- Propose changes as `calibration` proposals with a `config_patch` payload; `coach approve` applies the patch, updates
  the config lock and writes `state/changelog.md`. Approved rule changes also get a changelog line in
  `docs/TRAINING_ARCHITECTURE.md`. Review each trial at the end of its 4 weeks.

## Never
- Change config or thresholds without an approved proposal; cite anything not retrieved this run; run on Sundays.
