"""Re-evaluation audit (DECISIONS 104): the rule inventory and the review queue."""

import datetime as dt

TODAY = dt.date(2026, 11, 23)


def _rec(rule_id, value, **kw):
    from coach.models.records import EvidenceRecord

    base = dict(rule_id=rule_id, rule="r", value_at_review=value, reviewed=dt.date(2026, 5, 1))
    return EvidenceRecord(**{**base, **kw})


def test_inventory_walks_config_and_code_rules(home):
    from coach.config import load_config
    from coach.engine.audit import CODE_RULES, inventory

    cfg = load_config()
    ids = {r.rule_id for r in inventory(cfg)}
    assert "thresholds.hrv_below_days_red" in ids and "season.deload.volume_factor" in ids
    assert "progressions.rules.min_days_at_rung" in ids and "tests.typical_error_pct" in ids
    assert any(i.startswith("benchmarks.") for i in ids)
    assert set(CODE_RULES) <= ids
    assert "running.status" not in ids and "nutrition.supplements" not in ids  # data, not rules


def test_queue_unreviewed_changed_due_weak_orphaned(home):
    from coach.config import load_config
    from coach.engine.audit import audit, inventory

    cfg = load_config()
    inv = {r.rule_id: r for r in inventory(cfg)}
    hrv = inv["thresholds.hrv_below_days_red"].value
    deload = inv["season.deload.every"].value
    records = {
        # reviewed, unchanged, not due
        "season.deload.every": _rec("season.deload.every", deload, review_after=dt.date(2027, 5, 1)),
        # the config changed since the review
        "thresholds.hrv_below_days_red": _rec("thresholds.hrv_below_days_red", hrv + 1),
        # due again
        "thresholds.rhr_red_delta": _rec(
            "thresholds.rhr_red_delta",
            inv["thresholds.rhr_red_delta"].value,
            review_after=dt.date(2026, 11, 1),
        ),
        # weak evidence, high impact, kept: stays on the radar
        "code.red_carry_48h": _rec("code.red_carry_48h", None, evidence_level="practitioner", impact="high"),
        # a rule that no longer exists
        "thresholds.gone": _rec("thresholds.gone", 1),
    }
    q = audit(cfg, records, TODAY)
    assert q["rules"] == len(inv) and q["reviewed"] == 4
    assert [c["rule_id"] for c in q["changed_since_review"]] == ["thresholds.hrv_below_days_red"]
    assert q["due"] == ["thresholds.rhr_red_delta"]
    assert q["weak_evidence_high_impact"] == ["code.red_carry_48h"]
    assert q["orphaned_records"] == ["thresholds.gone"]
    assert "season.deload.every" not in q["unreviewed"] and "thresholds.rhr_yellow_delta" in q["unreviewed"]


def test_evidence_records_go_through_the_door_and_feed_the_cli(home):
    from coach import cli
    from coach.coaching import records
    from coach.config import load_config
    from coach.store import Store

    st, cfg = Store(), load_config()
    res = records.submit(
        st,
        cfg,
        "evidence",
        {
            "rule_id": "gear.shoe_alert_miles",
            "rule": "alert to replace shoes at 250 mi",
            "evidence_level": "practitioner",
            "impact": "low",
            "verdict": "keep_flagged",
            "sources": ["https://pmc.ncbi.nlm.nih.gov/articles/PMC5534152"],
            "value_at_review": cfg.profile.gear.get("shoe_alert_miles")
            if isinstance(cfg.profile.gear, dict)
            else cfg.profile.gear.model_dump().get("shoe_alert_miles"),
            "reviewed": "2026-11-23",
            "review_after": "2027-11-23",
        },
        TODAY,
    )
    assert res["saved"] == "evidence/gear.shoe_alert_miles"
    args = cli.build_parser().parse_args(["--date", "2026-11-23", "audit"])
    out = cli.COMMANDS["audit"](args)
    assert "gear.shoe_alert_miles" not in out["unreviewed"] and "inventory" not in out
    full = cli.COMMANDS["audit"](cli.build_parser().parse_args(["audit", "--full"]))
    assert any(r["rule_id"] == "code.red_carry_48h" for r in full["inventory"])
