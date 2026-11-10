"""plan-week fallback: outline week target -> detailed sessions (via design-session builders)."""

import datetime as dt
import math

from coach import clock
from coach.context import Context
from coach.engine import nutrition as nut
from coach.engine import testing as T
from coach.engine.running import RampRules, allowed_increase_cap
from coach.fallback import design as D
from coach.fallback.design import Picker, rx
from coach.fill import Filler
from coach.models import Deviation, RunSegment, Session, SessionBlock, WeekPlan

TEMPLATES = {
    1: ["lower_force", "upper_skill_metcon", "z2_run", "squat_hyrox", "sprint_upper", "long_run", "recovery"],
    2: [
        "lower_hyp",
        "upper_hyp_metcon",
        "z2_run",
        "lower_threshold",
        "upper_hyp_easy",
        "long_run",
        "recovery",
    ],
    3: [
        "lower_med_easy",
        "quality_run",
        "z2_upper_med",
        "hyrox_compromised",
        "easy_strides",
        "long_run",
        "recovery",
    ],
    4: ["lower_flush", "quality_run", "z2_run", "hyrox_short", "easy_strides", "long_run", "recovery"],
}
COMPETITION_OPEN = [
    "lower_moderate",
    "upper_skill_light",
    "z2_run",
    "recovery",
    "open_attempt",
    "easy_run",
    "recovery",
]
RACE_WEEK = ["full_light", "quality_short", "z2_run", "easy_strides", "rest", "shakeout", "race"]
RESET = ["full_light", "easy_run", "recovery", "full_light", "easy_run", "z2_bike", "recovery"]
TRANSITION = ["full_light", "z2_run", "recovery", "test_run", "test_strength", "test_engine", "recovery"]
BASELINE = ["test_lower", "test_upper", "z2_run", "test_run", "recovery", "test_engine", "recovery"]
RUN_SHARE = {
    "z2_run": 0.35,
    "sprint_upper": 0.25,
    "long_run": 0.40,
    "lower_threshold": 0.22,
    "upper_hyp_easy": 0.15,
    "lower_med_easy": 0.12,
    "quality_run": 0.18,
    "z2_upper_med": 0.18,
    "hyrox_compromised": 0.05,
    "easy_strides": 0.15,
    "easy_run": 0.35,
    "quality_short": 0.2,
    "shakeout": 0.1,
    "hyrox_short": 0.05,
}


def _sets(n: int, week_type: str) -> int:
    return max(1, math.floor(n * 0.55 + 0.5)) if week_type in D.DELOAD_LIKE else n


class WeekBuilder:
    def __init__(self, ctx: Context, week_start: dt.date, week_type: str, block_index: int):
        self.ctx = ctx
        self.start = week_start
        self.wt = week_type
        self.bi = block_index
        self.wn = week_start.isocalendar()[1]
        self.tests: dict[str, dt.date] = {}

    def P(self, location: str = "gym") -> Picker:
        return Picker(self.ctx, self.wt, location)

    def S(self, n: int) -> int:
        return _sets(n, self.wt)

    # ---------- lifting days ----------
    def lower_force(self, day, miles):
        P = self.P()
        hinge = P.main_lift("hinge")
        return D.make_session(
            self.ctx,
            day,
            "lower",
            "lower",
            "Lower force",
            "Heavy hinge 3-5 reps @ 2 RIR + single-leg + hamstrings",
            [
                D.warmup("lower", P),
                D.primer_lower(P),
                SessionBlock(
                    kind="strength",
                    title="Main lift",
                    items=D._items(
                        rx(hinge, self.S(4), 4, 2, rest_s=180),
                        rx(P.pick("bulgarian_split_squat"), self.S(3), 8, 2, per_side=True),
                    ),
                ),
                SessionBlock(
                    kind="hypertrophy",
                    title="Accessories",
                    items=D._items(
                        rx(P.pick("seated_leg_curl"), self.S(3), 10, 2),
                        rx(P.pick("calf_raise"), self.S(3), 12, 2),
                        rx(P.pick("copenhagen_plank"), 2, duration_s=20, per_side=True),
                    ),
                ),
                D.cooldown(P),
            ],
            key=True,
        )

    def lower_hyp(self, day, miles):
        P = self.P()
        sq = P.main_lift("squat")
        return D.make_session(
            self.ctx,
            day,
            "lower",
            "lower",
            "Lower hypertrophy",
            "Squat pattern 6-8 reps + leg volume",
            [
                D.warmup("lower", P),
                D.primer_lower(P),
                SessionBlock(kind="strength", items=D._items(rx(sq, self.S(4), 7, 2, rest_s=150))),
                SessionBlock(
                    kind="hypertrophy",
                    items=D._items(
                        rx(P.pick("rdl_db"), self.S(3), 10, 2),
                        rx(P.pick("leg_press"), self.S(3), 12, 2),
                        rx(P.pick("seated_leg_curl"), self.S(3), 12, 2),
                        rx(P.pick("hip_thrust"), self.S(3), 12, 2),
                        rx(P.pick("calf_raise"), self.S(3), 15, 2),
                    ),
                ),
                D.cooldown(P),
            ],
            key=True,
        )

    def lower_threshold(self, day, miles):
        P = self.P()
        hinge = P.main_lift("hinge")
        rep_mi = round(5 * 60 / self.ctx.zones.threshold_pace_s_per_mi, 2)
        reps = max(2, min(5, int(miles * 0.55 / rep_mi)))
        easy = max(0.5, round(miles - reps * rep_mi, 1))
        run = SessionBlock(
            kind="run",
            title="Threshold intervals",
            run=[
                RunSegment(label="Easy", zone="Z2", distance_mi=easy, terrain="treadmill"),
                RunSegment(
                    label="Threshold reps (5 min)",
                    zone="T",
                    distance_mi=rep_mi,
                    reps=reps,
                    recovery_min=1.5,
                    terrain="treadmill",
                ),
            ],
        )
        return D.make_session(
            self.ctx,
            day,
            "lower",
            "lower",
            "Lower + threshold run",
            "Hinge volume, then threshold intervals",
            [
                D.warmup("lower", P),
                SessionBlock(kind="strength", items=D._items(rx(hinge, self.S(3), 7, 2, rest_s=150))),
                SessionBlock(
                    kind="hypertrophy",
                    items=D._items(
                        rx(P.pick("bulgarian_split_squat"), self.S(3), 10, 2, per_side=True),
                        rx(P.pick("leg_extension"), self.S(3), 12, 2),
                    ),
                ),
                run,
                D.cooldown(P),
            ],
            key=True,
        )

    def squat_hyrox(self, day, miles):
        P = self.P()
        sq = P.main_lift("squat")
        return D.make_session(
            self.ctx,
            day,
            "squat-hyrox",
            "full_body",
            "Squat + Hyrox threshold",
            "Explosive primer, heavy squat, threshold Hyrox intervals",
            [
                D.warmup("full", P),
                D.primer_lower(P),
                SessionBlock(kind="strength", items=D._items(rx(sq, self.S(4), 5, 2, rest_s=180))),
                SessionBlock(kind="hypertrophy", items=D._items(rx(P.pick("hip_thrust"), self.S(3), 10, 2))),
                D.metcon_block(P, "hyrox", 20, self.wn),
                D.cooldown(P),
            ],
            key=True,
        )

    def upper_skill_metcon(self, day, miles):
        P = self.P()
        press = P.main_lift("press")
        return D.make_session(
            self.ctx,
            day,
            "upper",
            "upper",
            "Upper strength + skill + metcon",
            "Skill fresh, press + pull heavy, short metcon",
            [
                D.warmup("upper", P),
                D.skill_block(P, self.wn),
                SessionBlock(
                    kind="strength",
                    items=D._items(
                        rx(press, self.S(4), 5, 2, rest_s=150), rx(P.pick("strict_pull_up"), self.S(4), 5, 2)
                    ),
                ),
                SessionBlock(
                    kind="hypertrophy",
                    items=D._items(
                        rx(P.pick("chest_supported_db_row"), self.S(3), 10, 2),
                        rx(P.pick("lateral_raise_db"), self.S(3), 15, 2),
                        rx(P.pick("face_pull"), self.S(2), 15, 2),
                    ),
                ),
                D.metcon_block(P, "short", 10, self.wn),
                D.cooldown(P),
            ],
            key=True,
        )

    def upper_hyp_metcon(self, day, miles):
        P = self.P()
        press = P.main_lift("press")
        return D.make_session(
            self.ctx,
            day,
            "upper",
            "upper",
            "Upper hypertrophy + metcon",
            "Press/pull volume, short metcon",
            [
                D.warmup("upper", P),
                D.skill_block(P, self.wn),
                SessionBlock(
                    kind="strength",
                    items=D._items(rx(press, self.S(4), 8, 2), rx(P.pick("strict_pull_up"), self.S(4), 6, 2)),
                ),
                SessionBlock(
                    kind="hypertrophy",
                    items=D._items(
                        rx(P.pick("chest_supported_db_row"), self.S(4), 10, 2),
                        rx(P.pick("incline_db_press"), self.S(3), 10, 2),
                        rx(P.pick("lateral_raise_db"), self.S(4), 15, 2),
                        rx(P.pick("face_pull"), self.S(3), 15, 2),
                    ),
                ),
                D.metcon_block(P, "short", 10, self.wn),
                D.cooldown(P),
            ],
            key=True,
        )

    def sprint_upper(self, day, miles):
        P = self.P()
        return D.make_session(
            self.ctx,
            day,
            "sprint-upper",
            "sprint_upper",
            "Sprints + upper aesthetics + easy run",
            "Alactic sprints, upper hypertrophy, easy miles",
            [
                D.warmup("full", P),
                D.sprints(P),
                SessionBlock(
                    kind="hypertrophy",
                    items=D._items(
                        rx(P.pick("incline_db_press"), self.S(3), 10, 2),
                        rx(P.pick("lat_pulldown"), self.S(3), 10, 2),
                        rx(P.pick("cable_fly"), self.S(2), 12, 2),
                        rx(P.pick("rear_delt_fly_machine"), self.S(2), 15, 2),
                        rx(P.pick("db_curl"), self.S(2), 12, 2),
                        rx(P.pick("cable_triceps_pushdown"), self.S(2), 12, 2),
                    ),
                ),
                D.run_block("Easy treadmill run", miles, "Z2", "gym") if miles >= 1 else None,
                D.cooldown(P),
            ],
        )

    def upper_hyp_easy(self, day, miles):
        P = self.P()
        return D.make_session(
            self.ctx,
            day,
            "upper",
            "upper",
            "Upper hypertrophy + easy run",
            "Upper volume, then easy miles",
            [
                D.warmup("upper", P),
                D.primer_upper(P),
                SessionBlock(
                    kind="hypertrophy",
                    items=D._items(
                        rx(P.pick("iso_lateral_row"), self.S(4), 10, 2),
                        rx(P.pick("lat_pulldown"), self.S(3), 12, 2),
                        rx(P.pick("cable_fly"), self.S(3), 12, 2),
                        rx(P.pick("lateral_raise_db"), self.S(3), 15, 2),
                        rx(P.pick("db_curl"), self.S(3), 12, 2),
                        rx(P.pick("cable_triceps_pushdown"), self.S(3), 12, 2),
                    ),
                ),
                D.run_block("Easy run", miles, "Z2", "gym") if miles >= 1 else None,
                D.cooldown(P),
            ],
            key=False,
        )

    def lower_med_easy(self, day, miles):
        P = self.P()
        hinge = P.main_lift("hinge")
        return D.make_session(
            self.ctx,
            day,
            "lower",
            "lower",
            "Lower (MED) + easy run",
            "Maintain strength: trap bar + sled, easy miles after",
            [
                D.warmup("lower", P),
                SessionBlock(
                    kind="strength",
                    items=D._items(
                        rx(hinge, self.S(3), 5, 2), rx(P.pick("sled_push"), self.S(3), distance_m=25)
                    ),
                ),
                SessionBlock(
                    kind="hypertrophy", items=D._items(rx(P.pick("seated_leg_curl"), self.S(2), 10, 2))
                ),
                D.run_block("Easy run", miles, "Z2", "gym"),
                D.cooldown(P),
            ],
            key=True,
        )

    def z2_upper_med(self, day, miles):
        P = self.P("gym")
        press = P.main_lift("press")
        return D.make_session(
            self.ctx,
            day,
            "z2-upper",
            "upper",
            "Upper (MED) + Z2 run",
            "Maintain upper strength; aerobic volume",
            [
                D.warmup("full", P),
                SessionBlock(
                    kind="strength",
                    items=D._items(rx(press, self.S(3), 5, 2), rx(P.pick("strict_pull_up"), self.S(3), 5, 2)),
                ),
                SessionBlock(
                    kind="hypertrophy",
                    items=D._items(
                        rx(P.pick("chest_supported_db_row"), self.S(2), 10, 2),
                        rx(P.pick("lateral_raise_db"), self.S(2), 12, 2),
                    ),
                ),
                D.run_block("Zone 2 run", miles, "Z2", "gym"),
                D.cooldown(P),
            ],
        )

    def lower_flush(self, day, miles):
        P = self.P()
        hinge = P.main_lift("hinge")
        return D.make_session(
            self.ctx,
            day,
            "lower",
            "lower",
            "Lower flush",
            "Light strength to keep the pattern",
            [
                D.warmup("lower", P),
                SessionBlock(kind="strength", items=D._items(rx(hinge, 2, 3, 3))),
                D.cooldown(P),
            ],
        )

    def full_light(self, day, miles):
        P = self.P()
        return D.make_session(
            self.ctx,
            day,
            "full",
            "full_body",
            "Full body (light)",
            "Low-volume full body; keep moving, no fatigue",
            [
                D.warmup("full", P),
                SessionBlock(
                    kind="hypertrophy",
                    items=D._items(
                        rx(P.pick("goblet_squat"), 2, 8, 3),
                        rx(P.pick("hip_thrust"), 2, 10, 3),
                        rx(P.pick("db_bench_press_neutral"), 2, 8, 3),
                        rx(P.pick("chest_supported_db_row"), 2, 10, 3),
                    ),
                ),
                D.cooldown(P),
            ],
        )

    def lower_moderate(self, day, miles):
        P = self.P()
        hinge = P.main_lift("hinge")
        return D.make_session(
            self.ctx,
            day,
            "lower",
            "lower",
            "Lower (competition week)",
            "Keep strength, low volume",
            [
                D.warmup("lower", P),
                D.primer_lower(P),
                SessionBlock(kind="strength", items=D._items(rx(hinge, 3, 3, 2, rest_s=180))),
                SessionBlock(kind="hypertrophy", items=D._items(rx(P.pick("seated_leg_curl"), 2, 10, 2))),
                D.cooldown(P),
            ],
            key=True,
        )

    def upper_skill_light(self, day, miles):
        P = self.P()
        press = P.main_lift("press")
        return D.make_session(
            self.ctx,
            day,
            "upper",
            "upper",
            "Upper + skill (competition week)",
            "Sharp, low volume",
            [
                D.warmup("upper", P),
                D.skill_block(P, self.wn),
                SessionBlock(
                    kind="strength", items=D._items(rx(press, 3, 5, 2), rx(P.pick("strict_pull_up"), 3, 4, 3))
                ),
                D.cooldown(P),
            ],
        )

    # ---------- conditioning / runs ----------
    def hyrox_compromised(self, day, miles):
        P = self.P()
        return D.make_session(
            self.ctx,
            day,
            "hyrox",
            "hyrox",
            "Hyrox compromised running",
            "Run between stations at race effort",
            [
                D.warmup("run", P),
                D.metcon_block(P, "hyrox", 30, self.wn, "Hyrox compromised running"),
                D.cooldown(P),
            ],
            key=True,
        )

    def hyrox_short(self, day, miles):
        P = self.P()
        return D.make_session(
            self.ctx,
            day,
            "hyrox",
            "hyrox",
            "Hyrox sharpening",
            "Short race-pace stations",
            [D.warmup("run", P), D.metcon_block(P, "hyrox", 16, self.wn, "Hyrox sharpening"), D.cooldown(P)],
        )

    def z2_run(self, day, miles):
        P = self.P("outdoor")
        route = "farmington_river_trail" if self.wn % 2 else "west_hartford_reservoir"
        mob = SessionBlock(
            kind="mobility",
            title="Mobility + Copenhagen planks",
            items=D._items(
                rx(P.pick("hip_90_90"), 1, 8, per_side=True),
                rx(P.pick("copenhagen_plank_short"), 2, duration_s=20, per_side=True),
            ),
        )
        return D.make_session(
            self.ctx,
            day,
            "z2",
            "run_easy",
            "Zone 2 run",
            "Aerobic base at conversational effort (cadence 170-180)",
            [D.warmup("run", P), D.run_block("Zone 2 run", miles), mob, D.cooldown(P)],
            location="outdoor",
            route=route,
        )

    def easy_run(self, day, miles):
        P = self.P("outdoor")
        return D.make_session(
            self.ctx,
            day,
            "easy",
            "run_easy",
            "Easy run",
            "Easy aerobic miles",
            [D.warmup("run", P), D.run_block("Easy run", miles), D.cooldown(P)],
            location="outdoor",
            route="farmington_river_trail",
        )

    def easy_strides(self, day, miles):
        P = self.P("outdoor")
        return D.make_session(
            self.ctx,
            day,
            "easy",
            "run_easy",
            "Easy run + strides",
            "Easy miles, 6 relaxed strides",
            [D.warmup("run", P), D.run_block("Easy run", miles, strides=6), D.cooldown(P)],
            location="outdoor",
            route="farmington_river_trail",
        )

    def shakeout(self, day, miles):
        P = self.P("outdoor")
        return D.make_session(
            self.ctx,
            day,
            "shakeout",
            "run_easy",
            "Shakeout",
            "20 min easy + 4 strides",
            [D.warmup("run", P), D.run_block("Shakeout", max(1.5, miles), strides=4), D.cooldown(P)],
            location="outdoor",
            route="farmington_river_trail",
        )

    def z2_bike(self, day, miles):
        P = self.P()
        blk = SessionBlock(
            kind="run",
            title="Zone 2 bike",
            run=[RunSegment(label="BikeErg Z2", zone="Z2", duration_min=45, modality="bike")],
        )
        return D.make_session(
            self.ctx,
            day,
            "bike",
            "run_easy",
            "Zone 2 bike",
            "Zero-impact aerobic",
            [D.warmup("full", P), blk, D.cooldown(P)],
        )

    def quality_run(self, day, miles, short: bool = False):
        P = self.P("track")
        rep_min = 4 if short else 6
        rep_mi = round(rep_min * 60 / self.ctx.zones.threshold_pace_s_per_mi, 2)
        reps = max(2, min(5, int(miles * 0.45 / rep_mi)))
        cool = 0.8
        warm = max(1.0, round(miles - reps * rep_mi - cool, 1))
        seg = [
            RunSegment(label="Warm-up miles", zone="Z2", distance_mi=warm),
            RunSegment(
                label=f"Threshold reps ({rep_min} min)",
                zone="T",
                distance_mi=rep_mi,
                reps=reps,
                recovery_min=2,
            ),
            RunSegment(label="Cool-down jog", zone="Z1", distance_mi=cool),
        ]
        return D.make_session(
            self.ctx,
            day,
            "quality",
            "run_quality",
            "Threshold run",
            "Threshold reps at T pace (track, daylight)",
            [D.warmup("run", P), SessionBlock(kind="run", title="Threshold session", run=seg), D.cooldown(P)],
            location="track",
            route="canton_hs_track",
            key=True,
        )

    def quality_short(self, day, miles):
        return self.quality_run(day, miles, short=True)

    def long_run(self, day, miles):
        P = self.P("outdoor")
        mp = 20 if (self.bi >= 2 or miles >= 6) and self.wt == "training" else 0
        blocks = [D.warmup("run", P), D.run_block("Long run", miles, mp_finish_min=mp)]
        target_min = {1: 75, 2: 90, 3: 110, 4: 75}[self.bi]
        run_min = miles * self.ctx.zones.pace("Z2")[1] / 60
        if self.bi == 1 and run_min < target_min - 10 and self.wt == "training":
            extra = int(min(35, target_min - run_min))
            blocks.append(
                SessionBlock(
                    kind="run",
                    title="Erg extension (aerobic volume without impact)",
                    run=[
                        RunSegment(
                            label="Z2 bike (gym, after the run)",
                            zone="Z2",
                            duration_min=extra,
                            modality="bike",
                        )
                    ],
                )
            )
        blocks.append(D.cooldown(P))
        s = D.make_session(
            self.ctx,
            day,
            "long",
            "run_long",
            "Long run",
            "Progressive long run (Z2, marathon-pace finish when ready)",
            blocks,
            location="outdoor",
            route="farmington_river_trail",
            key=True,
        )
        return s

    def recovery(self, day, miles):
        return D.recovery_session(self.ctx, day)

    def rest(self, day, miles):
        return D.rest_session(self.ctx, day, "Rest before the race")

    def race(self, day, miles):
        P = self.P("outdoor")
        return D.make_session(
            self.ctx,
            day,
            "race",
            "race",
            "Race day",
            "Execute the race plan (state/events)",
            [D.warmup("run", P), D.run_block("Marathon", 26.2, "MP"), D.cooldown(P)],
            location="outdoor",
            key=True,
        )

    def open_attempt(self, day, miles):
        P = self.P()
        from coach.models import Metcon

        mc = Metcon(
            name="CrossFit Open workout (released Thursday)",
            format="for_time",
            time_cap_min=15,
            movements=[],
            stimulus="Compete: pacing plan from the compete skill once the workout is released",
            scaling="Rx only where every movement is at/below current rungs and competent skills; else scaled division",
            score_type="rounds_reps",
        )
        return D.make_session(
            self.ctx,
            day,
            "open",
            "competition",
            "Open attempt",
            "First attempt; re-attempt decision Monday",
            [
                D.warmup("full", P),
                SessionBlock(kind="conditioning", title="Open workout", metcon=mc),
                D.cooldown(P),
            ],
            key=True,
        )

    # ---------- tests ----------
    def _test_block(self, test_id: str, P: Picker) -> SessionBlock | None:
        t = self.ctx.cfg.tests.tests[test_id]
        if test_id == "broad_jump":
            items = D._items(rx(P.pick("broad_jump", block_kind="test"), 3, 1, rest_s=90))
        elif test_id == "hinge_rm":
            items = D._items(rx(P.main_lift("hinge"), 5, 5, 1, notes="work up to a 5RM at RPE 9"))
        elif test_id == "squat_rm":
            items = D._items(rx(P.main_lift("squat"), 5, 5, 1, notes="work up to a 5RM at RPE 9"))
        elif test_id == "db_press_5rm":
            items = D._items(
                rx(
                    P.pick("db_bench_press_neutral", block_kind="test"),
                    5,
                    5,
                    1,
                    notes="work up to a 5RM at RPE 9",
                )
            )
        elif test_id == "pullups_max":
            items = D._items(rx(P.pick("strict_pull_up", block_kind="test"), 1, notes="max strict reps"))
        elif test_id == "row_2k":
            items = D._items(rx(P.pick("row_erg", block_kind="test"), 1, distance_m=2000))
        else:
            items = []
        blk = SessionBlock(
            kind="test", title=t.name, test_id=test_id, items=items, notes=t.protocol.get("procedure", "")
        )
        return blk

    def _tests_on(self, day: dt.date) -> list[str]:
        return [t for t, d in self.tests.items() if d == day]

    def test_lower(self, day, miles):
        P = self.P()
        tests = self._tests_on(day)
        blocks = [
            D.warmup("lower", P),
            *[self._test_block(t, P) for t in sorted(tests, key=lambda t: T.TEST_RANK_ORDER(t, self.ctx))],
            D.cooldown(P),
        ]
        names = ", ".join(self.ctx.cfg.tests.tests[t].name for t in tests)
        return D.make_session(
            self.ctx,
            day,
            "test",
            "test",
            f"Test day: {names}",
            "Rep-max tests at current rungs (no true 1RMs)",
            blocks,
            key=True,
            tests=tests,
        )

    test_upper = test_lower
    test_strength = test_lower
    test_engine = test_lower

    def test_run(self, day, miles):
        P = self.P("outdoor")
        tests = self._tests_on(day)
        test_id = tests[0] if tests else "run_tt_30"
        if test_id == "run_submax_drift":
            seg = [
                RunSegment(label="Easy", zone="Z1", duration_min=10),
                RunSegment(label="Locked-HR drift run", zone="Z2", duration_min=30),
            ]
        else:
            seg = [
                RunSegment(label="Warm-up (15 min easy + strides)", zone="Z2", duration_min=15),
                RunSegment(label="30-min time trial", zone="T", duration_min=30),
            ]
        blk = SessionBlock(
            kind="test", title=self.ctx.cfg.tests.tests[test_id].name, test_id=test_id, run=seg
        )
        cd = D.cooldown(P)
        cd.run = [RunSegment(label="Cool-down jog", zone="Z1", duration_min=10)]
        return D.make_session(
            self.ctx,
            day,
            "test",
            "test",
            "Test day: run",
            "Threshold test: LTHR + threshold pace from the final 20 min",
            [D.warmup("run", P), blk, cd],
            location="outdoor",
            route="farmington_river_trail",
            key=True,
            tests=tests,
        )


def _tests_for_week(ctx: Context, week_type: str, block_index: int) -> list[str]:
    b = ctx.cfg.tests.batteries
    if week_type == "baseline":
        ids = list(b["baseline"])
        recent = ctx.trailing_miles(ctx.today, n=4)
        if recent and sum(recent) / len(recent) < 6:
            ids = [("run_submax_drift" if t == "run_tt_30" else t) for t in ids]
    else:
        ids = list(dict.fromkeys([*b["block_candidates"].get(f"B{block_index}", []), *b["always_tracked"]]))
    return [t for t in ids if not ctx.cfg.tests.tests[t].passive and t in TESTABLE]


TESTABLE = {
    "broad_jump",
    "hinge_rm",
    "squat_rm",
    "db_press_5rm",
    "pullups_max",
    "run_tt_30",
    "run_submax_drift",
    "row_2k",
}


def _roles(block_index: int, week_type: str) -> list[str]:
    if week_type == "baseline":
        return BASELINE
    if week_type == "transition":
        return TRANSITION
    if week_type == "competition":
        return COMPETITION_OPEN if block_index == 1 else RACE_WEEK
    if week_type == "reset":
        return RESET
    if week_type == "taper" and block_index == 4:
        return TEMPLATES[4]
    return TEMPLATES[block_index]


def plan_week(
    ctx: Context, week_start: dt.date, *, notes: list[str] | None = None, race_week: bool = False
) -> WeekPlan:
    macro = ctx.macro
    assert macro is not None, "macrocycle missing: run `coach macrocycle regenerate`"
    in_baseline = macro.baseline_start <= week_start <= macro.baseline_end
    block = None if in_baseline else macro.block_for(week_start)
    outline = ctx.state.outline(block.id) if block else None
    if not in_baseline and (block is None or outline is None):
        raise ValueError(f"no outline for week starting {week_start}")
    week_index = 0 if in_baseline else (week_start - block.start).days // 7 + 1  # type: ignore[union-attr]
    target = outline.week(week_index) if outline else None
    week_type = "baseline" if in_baseline else target.type  # type: ignore[union-attr]
    bi = block.index if block else 1
    if race_week or (
        block
        and block.index == 4
        and any(
            week_start <= d.date <= week_start + dt.timedelta(days=6)
            for d in ctx.cfg.profile.races
            if d.kind == "marathon"
        )
    ):
        roles = RACE_WEEK
    else:
        roles = _roles(bi, week_type)

    deviations: list[Deviation] = []
    # --- run volume: outline target, capped by the 10% rule over the trailing 3 normal weeks ---
    trailing = ctx.trailing_miles(week_start)
    if week_type == "baseline":
        run_total = 0.0
    else:
        run_total = target.run_miles  # type: ignore[union-attr]
        if week_type not in {"taper", "transition", "reset"}:
            cap = allowed_increase_cap(
                trailing, RampRules(start_miles=ctx.cfg.profile.running.ramp_start_miles)
            )
            if run_total > cap:
                deviations.append(
                    Deviation(
                        field="run_miles",
                        planned=f"{run_total:.1f}",
                        actual=f"{cap:.1f}",
                        reason=f"held to +10% over the trailing 3-week average ({', '.join(f'{m:g}' for m in trailing)} mi)",
                    )
                )
                run_total = cap
    shares = {r: RUN_SHARE[r] for r in roles if r in RUN_SHARE}
    th = ctx.cfg.profile.thresholds
    limit = (
        th.long_run_max_fraction
        if run_total >= th.long_run_rule_min_weekly_miles
        else th.long_run_max_fraction_low_volume
    )
    if "long_run" in shares:
        shares["long_run"] = min(shares["long_run"], limit - 0.02)
    total_share = sum(shares.values()) or 1
    miles_for = {r: round(run_total * shares[r] / total_share, 1) for r in shares}
    if week_type in {"baseline", "transition"}:
        miles_for = {r: 3.0 for r in shares}

    wb = WeekBuilder(ctx, week_start, week_type, bi)
    if week_type in {"baseline", "transition"}:
        tests = _tests_for_week(ctx, week_type, bi)
        wb.tests = T.schedule(
            week_start, tests, ctx.cfg.tests, "baseline" if week_type == "baseline" else "transition"
        )
    sessions: list[Session] = []
    for i, role in enumerate(roles):
        day = week_start + dt.timedelta(days=i)
        s = getattr(wb, role)(day, miles_for.get(role, 0.0))
        sessions.append(s)
    if target and target.hard_sets:
        D.balance_hard_sets(sessions, target.hard_sets, ctx, week_type)
    finalize(ctx, sessions)
    rationale = {
        "baseline": "Baseline week: full test battery spread so strength, run and engine tests fall on separate days.",
        "training": "Follows the block outline: main lifts fixed, accessories/metcons rotate.",
        "deload": "Planned deload: volume ~-45%, intensity kept, eccentric/high-impact work swapped.",
        "competition": "Competition week: freshness for the Open attempt; volume trimmed.",
        "transition": "Transition week: deload early, retest + next block's entry tests late, on separate days.",
        "taper": "Taper: volume down, intensity kept.",
        "reset": "Structural reset: easy, varied, low impact.",
    }[week_type]
    return WeekPlan(
        week_id=clock.iso_week_id(week_start),
        block_id=block.id if block else f"{macro.season}-B0",
        week_index=week_index,
        week_type=week_type,  # type: ignore[arg-type]
        start=week_start,
        sessions=sessions,
        deviations=deviations,
        generated_by="fallback",
        approval="pending",
        rationale=rationale + (" " + " ".join(notes) if notes else ""),
    )


def finalize(ctx: Context, sessions: list[Session]) -> None:
    """Minutes, carb tiers, loads and paces (code-computed numbers)."""
    hist = ctx.state.sessions(ctx.today - dt.timedelta(weeks=10), ctx.today)
    filler = Filler(ctx.cfg.library, ctx.cfg.equipment.loading, hist, ctx.zones, ctx.today)
    ordered = sorted(sessions, key=lambda s: s.date)
    for i, s in enumerate(ordered):
        s.expected_minutes = D.estimate_minutes(s, ctx.zones.threshold_pace_s_per_mi)
        tomorrow = ordered[i + 1] if i + 1 < len(ordered) else None
        s.carb_tier = nut.carb_tier_for(s, tomorrow)  # type: ignore[assignment]
        fams = {
            f
            for f, fs in ctx.movement.families.items()
            if fs.eccentric_tempo_until and fs.eccentric_tempo_until >= s.date
        }
        filler.fill(s, eccentric_families=fams)
