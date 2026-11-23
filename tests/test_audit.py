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
        "code.red_carry_48h": _rec(
            "code.red_carry_48h",
            inv["code.red_carry_48h"].value,
            evidence_level="practitioner",
            impact="high",
        ),
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


def test_code_rule_versions_changed_and_due_safety(home, monkeypatch):
    """Review of #20: a code rule's version bump shows as changed (changed wins over due); safety rules are listed."""
    from coach.config import load_config
    from coach.engine import audit as A

    cfg = load_config()
    v = A.CODE_RULES["code.red_carry_48h"][2]
    rec = _rec(
        "code.red_carry_48h",
        v,
        review_after=dt.date(2026, 1, 1),
        evidence_level="practitioner",
        impact="high",
    )
    q = A.audit(cfg, {"code.red_carry_48h": rec}, TODAY)
    assert q["due"] == ["code.red_carry_48h"] and not q["changed_since_review"]
    assert (
        "code.red_carry_48h" in q["safety_rules_queued"]
        and "thresholds.joint_red" in q["safety_rules_queued"]
    )
    where, what, _ = A.CODE_RULES["code.red_carry_48h"]
    monkeypatch.setitem(A.CODE_RULES, "code.red_carry_48h", (where, what, "v2"))
    q = A.audit(cfg, {"code.red_carry_48h": rec}, TODAY)
    assert [c["rule_id"] for c in q["changed_since_review"]] == ["code.red_carry_48h"]
    assert "code.red_carry_48h" not in q["due"]  # changed is reported once, ahead of due
    full = {r["rule_id"]: r for r in A.audit(cfg, {}, TODAY)["inventory"]}
    assert full["code.red_carry_48h"]["safety"] and not full["season.deload.every"]["safety"]
    assert set(full["code.red_carry_48h"]) == {"rule_id", "where", "value", "description", "safety"}


def test_dotted_rule_ids_round_trip_through_the_store(home):
    from coach.store import Store

    st = Store()
    for rid in ("code.red_carry_48h", "progressions.rules.min_days_at_rung"):
        st.put("evidence", _rec(rid, 1))
        assert st.get("evidence", rid).rule_id == rid
    assert sorted(st.keys("evidence")) == ["code.red_carry_48h", "progressions.rules.min_days_at_rung"]
