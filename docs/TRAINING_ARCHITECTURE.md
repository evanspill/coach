# Training architecture

The rules the coach follows. Skills reference this file instead of copying it; numbers come from `coach`
commands and `athlete/config/`. **Changes only through an approved proposal, with a changelog entry at the bottom.**


**Four pillars,** each with a build dose and a minimum effective dose (MED) depending on the block:
1. Neural power and elasticity: 10–15 min plyo/sprint primers before lower/full-body days.
2. Force and hypertrophy: 3–4 days/wk. Primary compound for 3–5 reps at 1–2 RIR, plus 8–15 rep accessories.
3. Glycolytic capacity: 2 sessions/wk (short metcon; Hyrox threshold simulation).
4. Aerobic base: Zone 2 run plus a progressive long run. 80/20 applies to running time-in-zone.

**Default microcycle** (a template; may shift within validator rules):
- Mon: neural primer, McGill Big 3, lower force (trap bar / safety squat bar) + leg hypertrophy.
- Tue: 10 min skill primer, upper strength/hypertrophy, ~10 min metcon.
- Wed: Z2 run 50–60 min; mobility, Copenhagen planks.
- Thu: explosive primer, Hyrox threshold simulation.
- Fri: alactic sprints (6×10 s on the Woodway Curve, or the track in good weather), upper/full-body aesthetics.
- Sat: progressive long run, 75–110 min (last 20–30 min at marathon pace).
- Sun: recovery (Z1 walk, mobility with foam roller/bands/lacrosse ball).

**Macrocycle** (dates from the generator; the dates below are illustrative):
- Baseline week (2026-11-16 → 11-22).
- Block 1, winter strength base → CrossFit Open (≈ 2026-11-23 → 2027-03-21): force build Nov–Jan, then ~5 weeks sharpening metcons and gymnastics into the Open. Running 12–15 mi/wk, outdoors when safe, with erg work covering the rest of the aerobic volume in bad weather. Calorie phase: set from the baseline body-composition measurement (cut, recomp, or lean gain toward 200 lb at 10–12%).
- Block 2, hypertrophy emphasis (12–16 hard sets/muscle/wk) plus run ramp from 15 to 25 mi/wk (≈ 03-22 → 06-27).
- Block 3, marathon build (35–50 mi/wk) plus Hyrox engine; lifting at MED (4–6 hard sets/muscle/wk), axial squats swapped for sleds/trap bar (≈ 06-28 → 09-26).
- Block 4, 3-week taper → marathon (10-17), optionally a late-autumn Hyrox → 2-week structural reset (≈ 09-27 → 10-31). The next cycle begins in November.
- Each block outline states the **MacroFactor goal setting** to use (chosen from the latest body-composition trend vs the 200 lb / 10–12% goal; Block 3 is normally maintenance/fuel-matched to support marathon training). The coach tells me when to change it, since MacroFactor has no write API.

**Pillar dose by block** (build = B, maintain = M; every pillar is trained every week):

| Pillar | Block 1 | Block 2 | Block 3 | Block 4 |
|---|---|---|---|---|
| Neural power | M: primers 2×/wk | M | M: strides/sprints 1×/wk | Sharpen: short race-pace bursts |
| Force/hypertrophy | **B (force)**: 4 d/wk, heavy 3–5 reps | **B (hypertrophy)**: 4 d/wk, 12–16 sets/muscle | M: 2–3 d/wk, 4–6 heavy sets/muscle | M/flush: 2 d/wk, light |
| Glycolytic | **B (Open peak)**: 2–3 metcons/wk | M: 1 metcon + 1 threshold | **B (Hyrox)**: compromised running | Race execution |
| Aerobic base | M: 12–15 mi/wk | Ramp 15→25 mi/wk | **B**: 35–50 mi/wk + long run | Taper + flush |

**Session structure (every session):** joint-specific warm-up → (skill primer if scheduled) → main work → cool-down → evening recovery note.
- *Upper/CrossFit days:* band pull-aparts, scapular push-ups, thoracic open-books, bottoms-up KB press.
- *Lower/run days:* McGill Big 3, tibialis raises, pogo hops, couch stretch.
- *Cool-down:* ~3 min easy movement with slow breathing until HR <110, then dead hangs.
- *Recovery prescription:* after high-strain days (e.g. Whoop strain >16, threshold or long runs), prescribe Normatec boots (20–30 min, at the gym post-session) and/or an evening soft-tissue/mobility routine using the foam roller, Theragun, lacrosse ball, and bands, targeted at the day's loaded areas. Magnesium at night. If cold exposure is ever added, keep it ≥4–6 h away from hypertrophy work.
- *Same-session order:* speed/power → heavy strength → hypertrophy → conditioning.

**Skill acquisition** (`athlete/config/skills.yaml`): Olympic lifts and gymnastics follow regression ladders (e.g. strict chest-to-bar and hollow/arch drills before kipping; overhead squat, hang positions, and muscle snatch before full lifts from the floor). Practice for 10–12 min when fresh (1–3 reps/set, ≤70% effort, stop when mechanics degrade). Never put unmastered skills in metcons. Overhead and kipping skills are also gated by the shoulder movement readiness rungs. Every 3–4 weeks the coach asks me to film a key lift or skill for a form check. Claude can review still frames I share; an in-person coach session is optional.

**Impact management:** shift part of conditioning volume onto zero-impact options (rower, SkiErg, air bike, sled), especially when weekly mileage exceeds ~35 mi.

**Return-to-running ramp:** start ≈10–12 mi/wk across 3 runs, cadence ≈170–180 spm, ≤10% weekly increase, and hold flat every 4th week.

**Variety:** I want training to stay varied and interesting. Main lifts stay fixed within a block (for progressive overload). Accessories, metcon formats, conditioning modalities, and run routes rotate across weeks and blocks, and `review` watches enjoyment scores.

**Progression:** set loads from recent e1RM. Add load when all target reps were hit at or above the target RIR. Hold or reduce after two missed sessions. Deloads cut volume ~40–50% and keep intensity.

**Readiness:**
- Daily: Whoop recovery score (≥67 green, 34–66 yellow, ≤33 red).
- Trend: 7-day mean of ln(rMSSD) compared with a 60-day baseline ± a smallest-worthwhile-change band (≈0.5 SD). RHR: 7-day mean compared with the 60-day baseline.
- **Green:** recovery ≥67 (or 34–66 with the HRV trend in/above the band), RHR within +3 bpm, joints ≤2. Run the plan as written.
- **Yellow:** recovery ≤33 today, OR 34–66 with the HRV trend below the band, OR HRV trend below the band ≥2 days, OR RHR +3–5 bpm. Keep primary strength; replace metcon/threshold work with 40 min Z2.
- **Red:** recovery ≤33 on 2 consecutive days, OR HRV trend below the band ≥3 days, OR RHR >+5 bpm, OR any joint ≥4, OR the same region ≥3 on 2 consecutive check-ins. Cut accessory volume 50%, make the next 48 h Z1 + mobility, and consider a reactive deload.
- **Joint rule:** a region rated ≥3 on 2 consecutive check-ins restricts that region's exercise tags, and those exercises are swapped using their regressions.
- The most restrictive state wins. Every decision has human-readable reasons. All thresholds come from config.

**Nutrition:** MacroFactor owns the weekly calorie target. The engine redistributes it across days (calorie-neutral): protein first, then the 100 g fat floor, then carbs. Carbs are high on hard days and the day before the long run, moderate on other training days, and lower on rest days (≈5.5 / 4 / 3 g/kg), scaled down proportionally if the total is tight.

**Evidence standard:** state confidence, never invent citations, and frame experiments as 4-week N=1 trials with a metric and a stop rule.


**Implementation notes** (see `docs/DECISIONS.md` for why): Block 1 runs 2026-11-23 -> 2027-03-14 (transition
week right after the Open); the long-run cap is 40% of weekly miles below 20 mi/week; Block 1's long-run
duration is topped up with Zone 2 bike; the +10% rule averages the last three normal weeks; rungs advance after
3 clean exposures and >= 14 days.

**Hard sets per muscle per week (block outline defaults):** Block 1 quads 8-16, hamstrings 6-14, glutes 8-18,
chest 6-14, back 10-20, shoulders 6-16; Block 2 12-16 (hamstrings 10-16, glutes 12-20); Block 3 4-9 (MED);
Block 4 2-8. Deload weeks ~40-65% of those.

## Keeping current with the science (monthly, `learn`)

On the first Wednesday of each month, the daily run also does a **science audit**. It searches recent literature (PubMed E-utilities and web search across high-signal sources such as ISSN position stands, *Sports Medicine*, *JSCR*, and research reviews), focused on my current block and open questions, and writes `athlete/data/science/YYYY-MM.md`. **A finding earns a proposal only if:**
1. it comes from a meta-analysis, systematic review, or multiple RCTs in trained humans;
2. its benefit outweighs the added complexity;
3. it's framed as a **4-week N=1 trial** with a hypothesis, metric, and stop rule.

Single studies, mouse studies, or hype never change my programming. Every cited paper must include a real PMID/DOI that the run actually retrieved. Proposals need my approval. Approved changes are written into `docs/TRAINING_ARCHITECTURE.md` with a changelog entry, and the trial result is reviewed at the end of the 4 weeks.


## Changelog
- 2026-11-10: initial version from the build brief (Phase 1).
