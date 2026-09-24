import pytest

from forget_lah.corpus.recording import (
    RECORDING_VERSION,
    RecordedModel,
    RecordingModel,
    observation_sha256,
    recording_document,
)
from forget_lah.runtime.provider import ModelError, ModelReply


class _Echo:
    """A stand-in real provider: deterministic, no network."""

    def __init__(self) -> None:
        self.calls = 0

    def decide(self, observation, *, repair=False):
        self.calls += 1
        return ModelReply(f"reply-{self.calls}", input_tokens=7, output_tokens=3, latency_ms=11)


def test_recording_model_delegates_and_records() -> None:
    records: list[dict] = []
    recorder = RecordingModel(_Echo(), records)
    first = recorder.decide({"request_id": "r1"}, repair=False)
    second = recorder.decide({"request_id": "r2"}, repair=True)

    assert first.text == "reply-1"
    assert second.text == "reply-2"
    assert [record["request_id"] for record in records] == ["r1", "r2"]
    assert records[1]["repair"] is True
    assert records[0]["observation_sha256"] == observation_sha256({"request_id": "r1"})
    assert records[0]["output_tokens"] == 3


def test_recorded_model_replays_in_order_and_verifies_observations() -> None:
    echo = _Echo()
    records: list[dict] = []
    RecordingModel(echo, records).decide({"request_id": "r1"})
    RecordingModel(echo, records).decide({"request_id": "r2"})

    replay = RecordedModel(records)
    assert replay.decide({"request_id": "r1"}).text == "reply-1"
    assert replay.decide({"request_id": "r2"}).text == "reply-2"
    assert replay.consumed == 2


def test_recorded_model_rejects_a_mismatched_observation() -> None:
    records: list[dict] = []
    RecordingModel(_Echo(), records).decide({"request_id": "r1"})
    with pytest.raises(ModelError, match="RECORDING_OBSERVATION_MISMATCH"):
        RecordedModel(records).decide({"request_id": "different"})


def test_recorded_model_refuses_to_invent_a_reply() -> None:
    with pytest.raises(ModelError, match="RECORDING_EXHAUSTED"):
        RecordedModel([]).decide({"request_id": "r1"})


def test_recording_document_shape() -> None:
    document = recording_document(
        "fam-ambiguous-01-en", "claude-sonnet-4-5", [], runtime_commit="abc1234"
    )
    assert document["recording_version"] == RECORDING_VERSION
    assert document["model_id"] == "claude-sonnet-4-5"
    assert document["variant_id"] == "fam-ambiguous-01-en"
    assert document["runtime_commit"] == "abc1234"
