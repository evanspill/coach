# Architecture

Diagrams from the build brief, updated where the implementation differs (noted under each).

## Architecture
```mermaid
flowchart TB
  subgraph Me["Me (iPad / iPhone)"]
    N[Push notification]
    S[Claude Code chat session]
  end
  subgraph Claude["Claude Code cloud"]
    T[Daily scheduled task 8:25 AM ET + 9:05 catch-up]
    E[Cloud environment: secrets + allowlist]
  end
  subgraph Repo["Private GitHub repo"]
    K[CLAUDE.md + skills]
    C[config/]
    P[coach package: engine + validator + push]
    ST[state/ = database]
  end
  subgraph APIs["External services"]
    W[Whoop]
    WS[Withings scale]
    H[Hevy]
    I[Intervals.icu]
    G[Garmin watch]
    M[Open-Meteo]
    NU[Nutrition export]
  end
  T --> K
  S --> K
  K --> P
  P <--> ST
  C --> P
  P -- via E --> W & WS & H & I & M & NU
  P -- validated plans --> H
  P -- validated workouts --> I
  I --> G
  G -- completed runs --> I
  T --> N
```
Whoop and Withings are reached through a small token broker (Phase 2) that holds their rotating refresh tokens.

## Daily run
```mermaid
flowchart TD
  A[Scheduled task starts] --> B[git pull]
  B --> C[coach sync]
  C --> D[coach status]
  D --> E{Paused?}
  E -- yes --> Z[Report only]
  E -- no --> RH[rehab: yesterday's exposures, pain, joint flags]
  RH --> MS{2+ missed sessions this week?}
  MS -- yes --> RP[replan: protect key sessions] --> F
  MS -- no --> F[Readiness + weather]
  F --> G[adjust-day + fuel + rehab swaps]
  G --> V1{validate}
  V1 -- fail, under 3 tries --> G
  V1 -- fail 3x --> FB[Fallback template]
  V1 -- pass --> P1[push today]
  FB --> P1
  P1 --> SR{Sustained Red or joint >= 4?}
  SR -- yes --> RD[replan: reactive deload proposal; auto if joint >= 4] --> H
  SR -- no --> H{Sunday?}
  H -- yes --> RV[review this week]
  RV --> X{Block transition due?}
  X -- yes --> R[assess: score tests -> review: block review -> assess: next goal -> approval -> plan-block]
  X -- no --> WK
  R --> WK[plan-week + design-session]
  WK --> V2{validate} --> AP{Approval mode}
  AP -- auto --> P2[push week]
  AP -- manual --> PEND[Mark pending proposal]
  H -- no --> SA
  P2 --> SA{First Wednesday of month?}
  PEND --> SA
  SA -- yes --> SCI[learn: science audit + calibration] --> CM
  SA -- no --> CM[Commit + push state]
  Z --> CM
  CM --> NT[Summary = push notification]
```
Differences from the brief: rehab runs before adjust-day (rung changes must be known before today's swaps);
the block transition runs *before* the Sunday plan-week, because the new block's first week needs its outline;
missed-session replans and reactive deloads are explicit steps.

## Planning layers
```mermaid
flowchart TD
  Y[Year: macrocycle from race dates] --> BL[Block: goal, guardrails, outline, deloads]
  BL --> WE[Week: detailed sessions, loads, paces]
  WE --> DA[Day: readiness + weather adjustments]
  DA -. results .-> WE
  WE -. adherence + progress .-> BL
  BL -. review .-> Y
```

## Block lifecycle
```mermaid
flowchart TD
  BW[Baseline week: full test battery] --> GO[Propose block goal + guardrails]
  GO --> OK{My approval}
  OK --> TW[Training weeks 3:1 with planned deloads]
  TW --> RD{Sustained Red or joint flag?}
  RD -- yes --> DL[Reactive deload, shift block] --> TW
  RD -- no --> TW
  TW --> TR[Transition week: deload, retest, next entry test]
  TR --> RV[Block review]
  RV --> GO
```

## Safety path
```mermaid
flowchart LR
  CL[Claude proposes plan] --> VA{coach validate}
  VA -- reasons --> CL
  VA -- pass --> PU[coach push]
  PU --> RV{re-validate inside push}
  RV -- fail --> STOP[Refuse + alert]
  RV -- pass --> EXT[Hevy / Intervals.icu / Garmin]
```

## Year timeline (as generated)
```mermaid
gantt
  dateFormat YYYY-MM-DD
  axisFormat %b
  section Testing
  Baseline week           :b0, 2026-11-16, 7d
  section Blocks
  Block 1 Strength to Open     :b1, 2026-11-23, 2027-03-14
  Block 2 Hypertrophy + run ramp :b2, 2027-03-15, 2027-06-27
  Block 3 Marathon + Hyrox     :b3, 2027-06-28, 2027-09-26
  Block 4 Taper race reset     :b4, 2027-09-27, 2027-10-31
  section Events
  CrossFit Open (reported) :milestone, 2027-02-18, 0d
  Marathon (placeholder)  :milestone, 2027-10-17, 0d
```
Block 1 ends one week after the last Open workout (`season.post_open_weeks: 1`), not two; see DECISIONS.md.

## Code map

| Module | Role |
|---|---|
| `coach/models/` | Pydantic models; `extra="forbid"` so Claude-written JSON can't smuggle fields |
| `coach/config.py` | Loads + cross-checks `config/` (every exercise/equipment/family reference must exist) |
| `coach/integrations/` | `base.py` ABCs, `normalize.py` (raw payload -> models, shared by mock + live), `mock.py`, `live.py` |
| `coach/sync.py` | Incremental, idempotent sync; merges Whoop + Hevy + Intervals into one session record |
| `coach/engine/` | readiness, loads, paces, weather, nutrition, macrocycle, deloads, running, testing, movement, gear, parsing |
| `coach/validator.py` | Every guardrail, with stable rule codes |
| `coach/fill.py` | Fills loads (e1RM -> rounded implement) and paces/HR (zones) into plans |
| `coach/push.py` | Hevy routines + Intervals events; always re-validates; dry-run unless `push.enabled` |
| `coach/proposals.py` | Proposals, approve/reject, config lock + changelog |
| `coach/fallback/` | Deterministic stand-in for each skill (used after 3 failed validations and in simulation) |
| `coach/daily.py` | The coach-daily flow in deterministic mode (`coach daily --fallback`, simulation) |
| `coach/sim/` | Simulated athlete, 120-day replay, per-skill scenarios |
