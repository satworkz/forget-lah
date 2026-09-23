"""Lane C acceptance tests for the cross-model benchmark replay.

Hermetic by construction: no test here performs live inference. Endpoints are faked with
`httpx.MockTransport`, and every scored number is asserted against hand-computed maths.
"""

import json

import httpx
import pytest

from forget_lah.runtime import decider_bench as bench

JEV = bench.Leg(
    name="jev-hosted",
    url="https://example.invalid/provider",
    model="typesafe/jev",
    billable=True,
    price_input_per_mtok=bench.JEV_INPUT_PRICE_USD_PER_MTOK,
    price_basis=bench.PRICE_BASIS_JEV,
)
LOCAL = bench.Leg(name="laya", url="http://127.0.0.1:8012", model="laya")


def choice_question():
    return {
        "type": "choice",
        "instructions": "Which team should handle this?",
        "criteria": {"billing": "refunds", "technical": "bugs", "sales": "pricing"},
    }


def score_question():
    return {"type": "score", "instructions": "How urgent?", "criteria": ["low", "mid", "high"]}


def noul_question():
    return {"type": "noul", "instructions": "Does this convey urgency?"}


def choice_answer(choice, probabilities, confidence=0.5):
    return {
        "type": "choice",
        "choice": choice,
        "probabilities": probabilities,
        "confidence": confidence,
    }


def gold_choice(label, probabilities):
    return {"type": "choice", "label": label, "probabilities": probabilities, "confidence": 0.5}


def test_leg_spec_parses_and_defaults():
    leg = bench.Leg.from_spec(json.dumps({"name": "laya", "url": "http://127.0.0.1:8012/"}))
    assert leg.name == "laya"
    assert leg.url == "http://127.0.0.1:8012"
    assert leg.model == "systemone"
    assert leg.billable is False


def test_leg_spec_rejects_incomplete():
    with pytest.raises(ValueError):
        bench.Leg.from_spec(json.dumps({"name": "laya"}))


def test_cost_is_zero_for_self_hosted_and_priced_for_hosted():
    assert LOCAL.cost_usd(1_000_000) == 0.0
    assert JEV.cost_usd(1_000_000) == pytest.approx(bench.JEV_INPUT_PRICE_USD_PER_MTOK)
    assert JEV.cost_usd(None) is None
    unpriced = bench.Leg(name="x", url="http://h", model="m", billable=True)
    assert unpriced.cost_usd(10) is None


@pytest.mark.parametrize(
    "url,expected",
    [
        ("http://127.0.0.1:8012", "http://127.0.0.1:8012/v1/systemone"),
        ("http://127.0.0.1:8012/", "http://127.0.0.1:8012/v1/systemone"),
        ("http://127.0.0.1:8012/v1/systemone", "http://127.0.0.1:8012/v1/systemone"),
    ],
)
def test_endpoint_accepts_base_or_full_route(url, expected):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"answers": {"q": {"type": "noul", "noul": 0.5}}})

    leg = bench.Leg(name="x", url=url, model="m")
    bench.post_systemone(
        leg, {"a": 1}, {"q": noul_question()}, transport=httpx.MockTransport(handler)
    )
    assert seen["url"] == expected


def test_post_systemone_sends_state_questions_and_bearer_without_echoing_key():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("Authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"answers": {"q": {"type": "noul", "noul": 0.7}}, "usage": {"input_tokens": 11}},
        )

    answers, usage, error, latency = bench.post_systemone(
        JEV,
        {"state": "s"},
        {"q": noul_question()},
        api_key="secret-token",
        transport=httpx.MockTransport(handler),
    )
    assert error is None
    assert captured["auth"] == "Bearer secret-token"
    assert captured["body"]["model"] == "typesafe/jev"
    assert captured["body"]["state"] == {"state": "s"}
    assert "q" in captured["body"]["questions"]
    assert answers == {"q": {"type": "noul", "noul": 0.7}}
    assert usage == {"input_tokens": 11}
    assert latency >= 0


def test_post_systemone_reports_http_and_envelope_failures():
    def status_handler(request):
        return httpx.Response(503, text="busy")

    assert (
        bench.post_systemone(
            LOCAL, "s", {"q": noul_question()}, transport=httpx.MockTransport(status_handler)
        )[2]
        == "http_503"
    )

    def junk_handler(request):
        return httpx.Response(200, text="not json")

    assert (
        bench.post_systemone(
            LOCAL, "s", {"q": noul_question()}, transport=httpx.MockTransport(junk_handler)
        )[2]
        == "envelope_invalid"
    )

    def no_answers_handler(request):
        return httpx.Response(200, json={"model": "laya"})

    assert (
        bench.post_systemone(
            LOCAL, "s", {"q": noul_question()}, transport=httpx.MockTransport(no_answers_handler)
        )[2]
        == "no_answers"
    )


def test_predicted_label_per_primitive():
    assert bench.predicted_label(choice_question(), choice_answer("billing", {})) == "billing"
    assert bench.predicted_label(noul_question(), {"type": "noul", "noul": 0.51}) == "true"
    assert bench.predicted_label(noul_question(), {"type": "noul", "noul": 0.49}) == "false"
    # score: the hard label is the argmax level index, not the expected level
    assert (
        bench.predicted_label(
            score_question(),
            {"type": "score", "score": 0.4, "probabilities": {"0": 0.7, "1": 0.2, "2": 0.1}},
        )
        == "0"
    )
    assert bench.predicted_label(noul_question(), {"type": "noul"}) is None
    assert bench.predicted_label(choice_question(), {"type": "choice"}) is None


def test_predicted_distribution_makes_noul_two_outcomes():
    assert bench.predicted_distribution(noul_question(), {"noul": 0.25}) == {
        "false": 0.75,
        "true": 0.25,
    }
    assert bench.predicted_distribution(
        choice_question(), {"probabilities": {"billing": 0.5, "sales": "x"}}
    ) == {"billing": 0.5}


def test_score_question_matches_hand_computed_brier_and_tv():
    question = choice_question()
    answer = choice_answer("billing", {"billing": 0.6, "technical": 0.3, "sales": 0.1})
    gold = gold_choice("billing", {"billing": 0.5, "technical": 0.25, "sales": 0.25})
    record = bench.score_question("team", question, answer, gold, {"argmax_agree": True})
    assert record["correct"] is True
    assert record["gold"] == "billing"
    assert record["predicted"] == "billing"
    assert record["gold_mass"] == 0.6
    expected_brier = ((0.6 - 0.5) ** 2 + (0.3 - 0.25) ** 2 + (0.1 - 0.25) ** 2) / 3
    assert record["brier"] == pytest.approx(round(expected_brier, 6))
    expected_tv = 0.5 * (abs(0.6 - 0.5) + abs(0.3 - 0.25) + abs(0.1 - 0.25))
    assert record["tv"] == pytest.approx(round(expected_tv, 6))
    assert record["teacher_agree"] is True
    assert record["score_mae"] is None


def test_score_question_scores_expected_level_error():
    question = score_question()
    answer = {"type": "score", "score": 1.75, "probabilities": {"0": 0.1, "1": 0.2, "2": 0.7}}
    gold = {
        "type": "score",
        "label": "1",
        "score": 1.0,
        "probabilities": {"0": 0.2, "1": 0.5, "2": 0.3},
    }
    record = bench.score_question("urgency", question, answer, gold)
    assert record["predicted"] == "2"  # argmax label
    assert record["correct"] is False  # gold label is 1
    assert record["score_mae"] == 0.75


def test_score_question_without_answer_is_unscored():
    record = bench.score_question("team", choice_question(), None, gold_choice("billing", {}))
    assert record["predicted"] is None
    assert record["correct"] is None
    assert record["brier"] is None


def test_score_question_noul_uses_two_outcome_distribution():
    answer = {"type": "noul", "noul": 0.8}
    gold = {
        "type": "noul",
        "label": "true",
        "noul": 0.6,
        "probabilities": {"false": 0.4, "true": 0.6},
    }
    record = bench.score_question("urgent", noul_question(), answer, gold)
    assert record["predicted"] == "true"
    assert record["correct"] is True
    expected_brier = ((0.2 - 0.4) ** 2 + (0.8 - 0.6) ** 2) / 2
    assert record["brier"] == pytest.approx(round(expected_brier, 6))


def test_aggregate_groups_by_primitive_and_workflow():
    records = [
        {
            "qid": "a",
            "qtype": "choice",
            "workflow": "wf1",
            "gold": "x",
            "predicted": "x",
            "correct": True,
            "brier": 0.1,
            "tv": 0.2,
            "gold_mass": 0.7,
            "score_mae": None,
        },
        {
            "qid": "b",
            "qtype": "choice",
            "workflow": "wf1",
            "gold": "y",
            "predicted": "x",
            "correct": False,
            "brier": 0.3,
            "tv": 0.4,
            "gold_mass": 0.1,
            "score_mae": None,
        },
        {
            "qid": "c",
            "qtype": "noul",
            "workflow": "wf2",
            "gold": "true",
            "predicted": "true",
            "correct": True,
            "brier": 0.05,
            "tv": 0.1,
            "gold_mass": 0.9,
            "score_mae": None,
        },
    ]
    outcomes = [
        bench.CallOutcome(leg="laya", status=bench.RAN, latency_ms=10, usage={"input_tokens": 5}),
        bench.CallOutcome(leg="laya", status=bench.RAN, latency_ms=30, usage={"input_tokens": 7}),
    ]
    summary = bench.aggregate(LOCAL, records, outcomes)
    assert summary["accuracy"] == pytest.approx(0.6667)
    assert summary["questions_answered"] == 3
    assert summary["questions_missing"] == 0
    assert summary["accuracy_by_primitive"]["choice"] == {"n": 2, "accuracy": 0.5}
    assert summary["accuracy_by_primitive"]["noul"] == {"n": 1, "accuracy": 1.0}
    assert summary["accuracy_by_workflow"]["wf1"] == {"n": 2, "accuracy": 0.5}
    assert summary["latency_ms"]["p50"] == 20.0
    assert summary["input_tokens"] == 12
    assert summary["priced_cost_usd"] == 0.0


def test_aggregate_counts_errors_without_scoring_them():
    summary = bench.aggregate(
        JEV,
        [
            {
                "qid": "a",
                "qtype": "choice",
                "workflow": "wf",
                "gold": "x",
                "predicted": None,
                "correct": None,
                "brier": None,
                "tv": None,
                "gold_mass": None,
                "score_mae": None,
            }
        ],
        [
            bench.CallOutcome(
                leg="jev-hosted", status=bench.ERROR, error_code="http_500", latency_ms=12
            )
        ],
    )
    assert summary["accuracy"] is None
    assert summary["questions_missing"] == 1
    assert summary["errors"] == {"http_500": 1}
    assert summary["priced_cost_usd"] is None  # hosted leg with no usage has no priceable cost


def test_reference_ceiling_reads_the_dataset_agreement_block():
    rows = [
        {
            "gold": {"a": {"label": "x"}, "b": {"label": "y"}},
            "agreement": {
                "a": {"argmax_agree": True, "argmax_majority": "x"},
                "b": {"argmax_agree": False, "argmax_majority": "z"},
            },
        },
        {
            "gold": {"a": {"label": "y"}},
            "agreement": {"a": {"argmax_agree": True, "argmax_majority": "y"}},
        },
    ]
    ceiling = bench.reference_ceiling(rows)
    assert ceiling["questions"] == 3
    assert ceiling["teacher_self_agreement"] == pytest.approx(0.6667)
    assert ceiling["teacher_argmax_vs_gold"] == pytest.approx(0.6667)


def test_load_rows_decodes_json_columns_and_skips_malformed(tmp_path):
    path = tmp_path / "bench.jsonl"
    good = {
        "id": "case-1",
        "workflow": "wf",
        "state": json.dumps({"a": 1}),
        "questions": json.dumps({"q": noul_question()}),
        "gold": json.dumps({"q": {"label": "true"}}),
        "label_agreement": json.dumps({"q": {"argmax_agree": True}}),
    }
    broken = {"id": "case-2", "state": "{}", "questions": "not json", "gold": "{}"}
    path.write_text(json.dumps(good) + "\n" + json.dumps(broken) + "\n" + "\n", encoding="utf-8")
    rows = bench.load_rows(path)
    assert len(rows) == 1
    assert rows[0]["state"] == {"a": 1}
    assert rows[0]["questions"]["q"]["type"] == "noul"
    assert rows[0]["agreement"]["q"]["argmax_agree"] is True


def test_run_replays_every_leg_and_exhausts_the_budget(tmp_path):
    rows = bench.load_rows(_write_fixture(tmp_path))
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(
            200,
            json={
                "answers": {"q": {"type": "noul", "noul": 0.9}},
                "usage": {"input_tokens": 100, "output_tokens": 0},
            },
        )

    transport = httpx.MockTransport(handler)
    result = bench.run([JEV, LOCAL], rows, tmp_path / "out", budget=1, transport=transport)
    hosted = next(leg for leg in result["legs"] if leg["leg"] == "jev-hosted")
    local = next(leg for leg in result["legs"] if leg["leg"] == "laya")
    assert result["budget"]["billable"] == 1
    assert result["budget"]["remaining"] == 0
    assert hosted["calls"] == 2
    assert hosted["calls_ok"] == 1
    assert hosted["skipped"] == {"budget_exhausted": 1}
    assert local["calls_ok"] == 2
    assert local["accuracy"] == 1.0
    assert calls["n"] == 3  # one hosted + two local
    assert (tmp_path / "out" / "results.json").exists()
    assert (tmp_path / "out" / "records-laya.jsonl").read_text().count("\n") == 2


def test_summarise_states_that_accuracy_is_benchmark_agreement():
    result = {
        "ceiling": {
            "teacher_self_agreement": 0.735,
            "teacher_argmax_vs_gold": 0.7,
            "questions": 10,
        },
        "legs": [
            {
                "leg": "laya",
                "accuracy": 0.75,
                "questions_answered": 10,
                "brier": 0.06,
                "latency_ms": {"p50": 900},
                "errors": {},
            }
        ],
    }
    text = bench.summarise(result)
    assert "0.735" in text
    assert "laya" in text
    assert "synthetic gold labels" in text


def _write_fixture(tmp_path):
    path = tmp_path / "bench.jsonl"
    row = {
        "id": "case-1",
        "workflow": "wf",
        "state": json.dumps({"a": 1}),
        "questions": json.dumps({"q": noul_question()}),
        "gold": json.dumps(
            {"q": {"label": "true", "noul": 0.7, "probabilities": {"false": 0.3, "true": 0.7}}}
        ),
        "label_agreement": json.dumps({"q": {"argmax_agree": True, "argmax_majority": "true"}}),
    }
    path.write_text(json.dumps(row) + "\n" + json.dumps(row) + "\n", encoding="utf-8")
    return path
