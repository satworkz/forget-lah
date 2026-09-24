import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from test_adaptation import BarrierModel, add_slot
from test_patient_simulation import simulated_runtime as simulated_runtime
from test_patient_simulation import source_count
from test_runtime import drain, event, headers, start, view
from test_simulator import simulator as simulator

from forget_lah.worker import run_lanes


def test_blocked_agent_does_not_block_delivery_or_second_agent():
    stopped = threading.Event()
    blocked = threading.Event()
    release = threading.Event()
    delivered = threading.Event()
    other_case = threading.Event()

    def slow_agent():
        blocked.set()
        assert release.wait(5)
        return False

    def delivery():
        if blocked.is_set():
            delivered.set()
        return False

    def fast_agent():
        if blocked.is_set():
            other_case.set()
        return False

    with ThreadPoolExecutor(max_workers=1) as pool:
        worker = pool.submit(
            run_lanes,
            [("slow", slow_agent), ("channel", delivery), ("other", fast_agent)],
            stopped,
            0.01,
        )
        try:
            assert blocked.wait(2)
            assert delivered.wait(2)
            assert other_case.wait(2)
        finally:
            stopped.set()
            release.set()
        worker.result(timeout=5)


def test_unexpected_lane_failure_stops_supervisor():
    stopped = threading.Event()

    def fail():
        raise RuntimeError("test failure")

    with pytest.raises(RuntimeError, match="test failure"):
        run_lanes([("broken", fail), ("healthy", lambda: False)], stopped, 0.01)
    assert stopped.is_set()


def test_required_reads_reduce_calls_without_changing_offer(simulated_runtime):
    class CountingModel(BarrierModel):
        calls = 0

        def decide(self, observation, **kwargs):
            self.calls += 1
            return super().decide(observation, **kwargs)

    runtime, tools, source, engine = simulated_runtime
    add_slot(source, 10)
    chosen = add_slot(source, 17)
    results = []
    case = None
    for enabled in (False, True):
        runtime[2].agent_required_reads_enabled = enabled
        if case is None:
            case, _ = start(runtime, "myopia")
        else:
            runtime[1].post(
                f"/api/cases/{case}/agent/runs",
                headers=headers(runtime[1]),
                json={
                    "expected_case_version": view(runtime[1], case)["case_version"],
                    "fresh_simulation": True,
                },
            ).raise_for_status()
        model = CountingModel()
        drain(runtime, tools=tools, model=model)
        event(runtime[1], case, "demo_reply", "Only after 3 pm please").raise_for_status()
        drain(runtime, tools=tools, model=model)
        result = view(runtime[1], case)
        assert result["run"]["status"] == "waiting" and not result["handoff"]
        offer = result["patient_simulator"]["messages"][-1]
        assert [s["id"] for s in offer["evidence"]["slots"]] == [chosen]
        reads = [
            s
            for s in result["steps"]
            if s["role"] in {"engagement", "preparation"}
            and s.get("tool_result")
            and s["tool_result"]["tool_name"]
            in {"read_followup_context", "get_approved_instructions", "check_prerequisites"}
        ]
        if enabled:
            assert all(s["origin"] == "rule" and s["attempts"] == 0 for s in reads)
            sends = [
                s
                for s in result["steps"]
                if (s.get("decision") or {}).get("tool_name") == "send_simulated_options"
            ]
            assert len(sends) == 1 and sends[0]["origin"] == "rule"
            assert sends[0]["attempts"] == 0
        results.append((model.calls, offer["original_body"]))
    assert results[0][1] == results[1][1]
    assert results[0][0] - results[1][0] == 4
    assert source_count(engine) == 0
    print("Equivalent slot-offer model calls:", results[0][0], "->", results[1][0])
