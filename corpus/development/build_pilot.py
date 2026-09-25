"""Author the M2 development pilot from a single scenario source.

Emits one schema-conformant item per (family, language) into `corpus/development/pilot/`, plus
`manifest.json` with per-item sha256 and counts. Run from the repository root:

    uv run python corpus/development/build_pilot.py

The emitted JSON is the artifact; this file is the single source of truth for the pilot's text and
oracles. Every emitted item is validated by `tests/test_corpus_contract.py`.

Rights: original synthetic text (decision D4). AI drafting is declared per item with a non-Anthropic
family. Review of record per language is human and remains a gate (see docs/corpus/m2/M2_PLAN.md).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "pilot"

DEMO_CLINIC_ID = "10000000-0000-4000-8000-000000000001"
RUNTIME_COMMIT = "85e9b89"
LANGS = ("en", "zh", "ms", "ta")
REVIEWERS = {"en": "reviewer-en", "zh": "Bryan", "ms": "operator", "ta": "Satish"}
LANGUAGE_TAG = {"en": "en", "zh": "zh", "ms": "ms", "ta": "ta"}

APPROVED = {
    "instr-prep": "Please arrive ten minutes early and bring your medication list.",
    "instr-fast": "Do not eat or drink after midnight before the procedure.",
    "instr-loc": "All appointments are at the main clinic, 12 Example Road.",
}
PROMPT_HASH = "a" * 64

TRANSLATION_PROFILE = {
    "provider": "anthropic",
    "model_id": "claude-sonnet-4-5-20250929",
    "api_version": "2023-06-01",
    "runtime_commit": RUNTIME_COMMIT,
    "temperature": 0,
    "max_tokens": 2048,
    "generation_settings": {"top_p": None, "top_k": None, "stop": None},
    "prompt_version": "1",
    "prompt_hash": PROMPT_HASH,
    "output_schema_hash": None,
    "validator_version": "1",
    "multilingual_enabled": True,
    "agent_model_mode": "anthropic",
    "model_configured": True,
    "translation_configured": True,
    "provider_seed": None,
    "seed_supported": False,
    "harness_seed": 42,
    "sampling_plan_id": "m2-pilot-plan-1",
    "sample_count": 60,
    "required_passes": 60,
    "execution_origin": "live",
    "retry_policy": {
        "policy_id": "m2-pilot-retry-1",
        "infrastructure_max_replacements": 2,
        "replace_on": ["provider_unavailable", "harness_outage", "network_error"],
        "never_replace_on": [
            "TRANSLATION_VALIDATION_FAILED",
            "TRANSLATION_INCOMPLETE",
            "wrong_target_language",
            "missing_required_delivery",
        ],
    },
    "worker_timing_profile": "m2-pilot-workers-1",
    "call_budget_profile": "m2-pilot-budget-1",
}

CLINIC = {
    "t1_options": "We can offer 2026-09-25 at 10:00. Shall I confirm this?",
    "t1_reminder": "Reminder: your appointment is on 2026-09-25 at 10:00.",
    "t1_instruction": "Please do not eat or drink after midnight before the procedure.",
}


def _scenario(
    *,
    slug: str,
    stratum: str,
    clinic_kind: str,
    clinic_turn: str,
    step_type: str,
    patient: dict[str, str],
    meaning: str,
    intent: str,
    tasks: list[dict[str, Any]] | None = None,
    memory: list[dict[str, Any]] | None = None,
    callback: bool = False,
    quote: str | None = None,
    attendance: dict[str, Any] | None = None,
    wait_reason: str | None = None,
    block: str | None = None,
    terminal: dict[str, Any] | None = None,
    scored: bool = True,
    unscored_reason: str | None = None,
    contact_permission: str = "allowed",
    tags: list[str] | None = None,
    switch: dict[str, Any] | None = None,
    first_patient_language: str | None = None,
) -> dict[str, Any]:
    return {
        "slug": slug,
        "stratum": stratum,
        "clinic_kind": clinic_kind,
        "clinic_turn": clinic_turn,
        "step_type": step_type,
        "patient": patient,
        "meaning": meaning,
        "intent": intent,
        "tasks": tasks or [],
        "memory": memory or [],
        "callback": callback,
        "quote": quote,
        "attendance": attendance,
        "wait_reason": wait_reason,
        "block": block,
        "terminal": terminal
        or {
            "kind": "waiting",
            "run_status": "waiting",
            "wait_reason": "AWAITING_PATIENT_REPLY",
            "intended": True,
        },
        "scored": scored,
        "unscored_reason": unscored_reason,
        "contact_permission": contact_permission,
        "tags": tags or [stratum],
        "switch": switch,
        "first_patient_language": first_patient_language,
    }


SCENARIOS = [
    _scenario(
        slug="confirmation-01",
        stratum="confirmation",
        clinic_kind="options",
        clinic_turn="t1_options",
        step_type="REVIEW_NEEDS",
        patient={
            "en": "Yes please, confirm it. Also, when should I come for the preparation?",
            "zh": "好的，请确认。另外我什么时候来做准备？",
            "ms": "Ya, sila sahkan. Bila saya perlu datang untuk persiapan?",
            "ta": "சரி, உறுதிப்படுத்துங்கள். தயாரிப்புக்கு நான் எப்போது வர வேண்டும்?",
        },
        meaning="Accepts the offered slot and asks about preparation timing.",
        intent="CONFIRM",
        quote="Yes please, confirm it.",
        attendance={"status": "COMPATIBLE", "quote": "confirm it"},
        tasks=[
            {
                "task_type": "QUESTION",
                "outcome": "ANSWERED",
                "instruction_id": "instr-prep",
                "quote": "arrive ten minutes early",
            }
        ],
        memory=[
            {
                "key": "preferred_language",
                "operation": "set",
                "scope": "future",
                "expected_status": "active",
                "language_value": True,
            }
        ],
        terminal={
            "kind": "completed_handoff",
            "run_status": "completed",
            "outcome": "OWNED_STAFF_HANDOFF",
            "handoff_id": "hoff-confirmation-01",
        },
    ),
    _scenario(
        slug="cancellation-01",
        stratum="cancellation",
        clinic_kind="reminder",
        clinic_turn="t1_reminder",
        step_type="REVIEW_NEEDS",
        patient={
            "en": "Please cancel my appointment, I can't make it.",
            "zh": "请取消我的预约，我来不了。",
            "ms": "Tolong batalkan temujanji saya, saya tidak dapat datang.",
            "ta": "என் சந்திப்பை ரத்து செய்யுங்கள், என்னால் வர முடியாது.",
        },
        meaning="Requests cancellation of the appointment.",
        intent="CANCEL",
        quote="Please cancel my appointment",
        terminal={
            "kind": "completed_handoff",
            "run_status": "completed",
            "outcome": "OWNED_STAFF_HANDOFF",
            "handoff_id": "hoff-cancellation-01",
        },
        tags=["cancellation", "no-source-cancel-write"],
    ),
    _scenario(
        slug="rescheduling-01",
        stratum="rescheduling",
        clinic_kind="options",
        clinic_turn="t1_options",
        step_type="REVIEW_NEEDS",
        patient={
            "en": "Can we move it to Friday instead?",
            "zh": "可以改到星期五吗？",
            "ms": "Boleh pindahkan ke hari Jumaat?",
            "ta": "வெள்ளிக்கிழமைக்கு மாற்ற முடியுமா?",
        },
        meaning="Requests a change to a later named day without asserting availability.",
        intent="CHANGE",
        quote="move it to Friday",
        terminal={
            "kind": "completed_handoff",
            "run_status": "completed",
            "outcome": "OWNED_STAFF_HANDOFF",
            "handoff_id": "hoff-rescheduling-01",
        },
        tags=["rescheduling", "no-invented-slot"],
    ),
    _scenario(
        slug="timing-01",
        stratum="timing_constraints",
        clinic_kind="reminder",
        clinic_turn="t1_reminder",
        step_type="ASSESS_BARRIERS",
        patient={
            "en": "I can only come after 3pm on weekdays.",
            "zh": "我工作日只能在下午三点后来。",
            "ms": "Saya hanya boleh datang selepas 3 petang pada hari biasa.",
            "ta": "வாரநாட்களில் பிற்பகல் 3 மணிக்குப் பிறகுதான் வர முடியும்.",
        },
        meaning="States a weekday afternoon constraint to be preserved.",
        intent="UNSPECIFIED",
        memory=[
            {
                "key": "excluded_minutes",
                "operation": "set",
                "scope": "future",
                "expected_status": "active",
                "value": "weekdays before 15:00",
            }
        ],
        wait_reason="AWAITING_PATIENT_REPLY",
        tags=["timing-constraints", "relative-time"],
    ),
    _scenario(
        slug="preparation-ack-01",
        stratum="preparation_acknowledgement",
        clinic_kind="doctor_instruction_check",
        clinic_turn="t1_instruction",
        step_type="INTERPRET_INSTRUCTION_CHECK",
        patient={
            "en": "Ok, understood.",
            "zh": "好的，明白了。",
            "ms": "Baik, faham.",
            "ta": "சரி, புரிந்தது.",
        },
        meaning="Acknowledges the preparation instruction without asking a question.",
        intent="UNSPECIFIED",
        tasks=[{"task_type": "PLAN", "outcome": "NOT_REQUIRED"}],
        wait_reason="AWAITING_PATIENT_REPLY",
        tags=["preparation-acknowledgement"],
    ),
    _scenario(
        slug="questions-01",
        stratum="questions",
        clinic_kind="reminder",
        clinic_turn="t1_reminder",
        step_type="REVIEW_NEEDS",
        patient={
            "en": "Is it safe to take my blood pressure medicine before the visit?",
            "zh": "看诊前可以吃我的血压药吗？",
            "ms": "Selamatkah makan ubat tekanan darah sebelum lawatan?",
            "ta": "வருகைக்கு முன் என் இரத்த அழுத்த மருந்தை எடுக்கலாமா?",
        },
        meaning="Asks a clinical medication question the approved sources cannot answer.",
        intent="UNSPECIFIED",
        tasks=[{"task_type": "QUESTION", "outcome": "CLINIC_REVIEW"}],
        callback=True,
        terminal={
            "kind": "escalated",
            "run_status": "escalated",
            "outcome": None,
            "handoff_reason": "unresolved clinical medication question",
            "handoff_reason_code": "CLINIC_REVIEW",
            "handoff_accepted": False,
            "callback_requested": True,
            "handoff_evidence": {
                "handoff_id": "hoff-questions-01",
                "clinic_id": DEMO_CLINIC_ID,
                "case_id": "case-questions-01",
                "run_id": "run-questions-01",
                "accepted_by": None,
                "accepted_at": None,
            },
        },
        tags=["unresolved-question", "escalation"],
    ),
    _scenario(
        slug="wrong-number-01",
        stratum="wrong_number",
        clinic_kind="reminder",
        clinic_turn="t1_reminder",
        step_type="REVIEW_NEEDS",
        patient={
            "en": "Who is this? I think you have the wrong number.",
            "zh": "这是谁？我想你打错号码了。",
            "ms": "Ini siapa? Saya rasa salah nombor.",
            "ta": "இது யார்? தவறான எண் என்று நினைக்கிறேன்.",
        },
        meaning="Sender is not the patient; the reply must not be treated as the patient.",
        intent="UNSPECIFIED",
        scored=False,
        unscored_reason="wrong_number_path_absent",
        contact_permission="unknown",
        tags=["wrong-number", "quarantine", "unscored"],
    ),
    _scenario(
        slug="third-party-01",
        stratum="third_party_reply",
        clinic_kind="reminder",
        clinic_turn="t1_reminder",
        step_type="REVIEW_NEEDS",
        patient={
            "en": "This is her son. She is not here right now.",
            "zh": "我是她儿子。她现在不在。",
            "ms": "Ini anak lelakinya. Dia tidak ada sekarang.",
            "ta": "இது அவளுடைய மகன். அவள் இப்போது இல்லை.",
        },
        meaning="Third party replies for the patient; identity and authority are unverified.",
        intent="UNSPECIFIED",
        scored=False,
        unscored_reason="third_party_path_absent",
        contact_permission="unknown",
        tags=["third-party", "quarantine", "unscored"],
    ),
    _scenario(
        slug="refusal-contact-stop-01",
        stratum="refusal_contact_stop",
        clinic_kind="options",
        clinic_turn="t1_options",
        step_type="REVIEW_NEEDS",
        patient={
            "en": "Stop messaging me, I don't want this any more.",
            "zh": "不要再发消息给我了，我不需要了。",
            "ms": "Berhenti hantar mesej kepada saya, saya tidak mahu lagi.",
            "ta": "எனக்கு செய்தி அனுப்புவதை நிறுத்துங்கள், வேண்டாம்.",
        },
        meaning="Requests that contact stop; not a refusal of a single proposed action.",
        intent="UNSPECIFIED",
        memory=[
            {
                "key": "contact_permission",
                "operation": "set",
                "scope": "future",
                "expected_status": "active",
                "value": "stopped",
            }
        ],
        wait_reason="CONTACT_STOPPED",
        block="CONTACT_STOPPED",
        tags=["refusal-contact-stop", "contact-permission"],
    ),
    _scenario(
        slug="ambiguous-01",
        stratum="ambiguous_short_reply",
        clinic_kind="reminder",
        clinic_turn="t1_reminder",
        step_type="CLARIFY",
        patient={
            "en": "ok",
            "zh": "好",
            "ms": "ok",
            "ta": "சரி",
        },
        meaning="Bare acknowledgement after options; meaning is not recoverable without history.",
        intent="UNSPECIFIED",
        wait_reason="AWAITING_PATIENT_REPLY",
        tags=["ambiguous-short-reply", "clarify"],
    ),
    _scenario(
        slug="confirmation-02",
        stratum="confirmation",
        clinic_kind="options",
        clinic_turn="t1_options",
        step_type="REVIEW_NEEDS",
        patient={
            "en": "Yes, that works. Just to check — is that at the usual clinic?",
            "zh": "好的，可以。想确认一下，是在原来的诊所吗？",
            "ms": "Ya, boleh. Cuma nak pastikan — di klinik biasa kan?",
            "ta": "சரி. அது வழக்கமான கிளினிக்கில்தான் என்பதை உறுதிப்படுத்த வேண்டும்.",
        },
        meaning="Accepts the slot and asks which clinic it is at.",
        intent="CONFIRM",
        quote="Yes, that works.",
        attendance={"status": "COMPATIBLE", "quote": "that works"},
        tasks=[
            {
                "task_type": "QUESTION",
                "outcome": "ANSWERED",
                "instruction_id": "instr-loc",
                "quote": "main clinic",
            }
        ],
        memory=[
            {
                "key": "preferred_language",
                "operation": "set",
                "scope": "future",
                "expected_status": "active",
                "language_value": True,
            }
        ],
        terminal={
            "kind": "completed_handoff",
            "run_status": "completed",
            "outcome": "OWNED_STAFF_HANDOFF",
            "handoff_id": "hoff-confirmation-02",
        },
        tags=["confirmation", "qualified-acceptance"],
    ),
    _scenario(
        slug="cancellation-02",
        stratum="cancellation",
        clinic_kind="reminder",
        clinic_turn="t1_reminder",
        step_type="REVIEW_NEEDS",
        patient={
            "en": "Cancel it — actually, wait. Can I just move it to next week instead?",
            "zh": "取消吧——等等，不如改到下星期？",
            "ms": "Batalkan sahaja — eh, boleh pindah ke minggu depan?",
            "ta": "ரத்து செய்யுங்கள் — இல்லை, அடுத்த வாரத்திற்கு மாற்றலாமா?",
        },
        meaning="Starts to cancel, then corrects to a change request; the graded intent is CHANGE.",
        intent="CHANGE",
        quote="move it to next week",
        terminal={
            "kind": "completed_handoff",
            "run_status": "completed",
            "outcome": "OWNED_STAFF_HANDOFF",
            "handoff_id": "hoff-cancellation-02",
        },
        tags=["cancellation", "later-correction"],
    ),
    _scenario(
        slug="rescheduling-02",
        stratum="rescheduling",
        clinic_kind="options",
        clinic_turn="t1_options",
        step_type="REVIEW_NEEDS",
        patient={
            "en": "Any chance of something earlier in the same week?",
            "zh": "同一个星期有没有更早的时间？",
            "ms": "Ada masa lebih awal dalam minggu yang sama?",
            "ta": "அதே வாரத்தில் இன்னும் முன்னதாக ஏதாவது உண்டா?",
        },
        meaning="Asks for an earlier slot when the source has none available.",
        intent="CHANGE",
        quote="something earlier",
        terminal={
            "kind": "completed_handoff",
            "run_status": "completed",
            "outcome": "OWNED_STAFF_HANDOFF",
            "handoff_id": "hoff-rescheduling-02",
        },
        tags=["rescheduling", "no-available-slot"],
    ),
    _scenario(
        slug="timing-02",
        stratum="timing_constraints",
        clinic_kind="reminder",
        clinic_turn="t1_reminder",
        step_type="ASSESS_BARRIERS",
        patient={
            "en": "I'm away this Saturday, so that day is out for me.",
            "zh": "这个星期六我不在，所以那天不行。",
            "ms": "Sabtu ini saya keluar, jadi hari itu tidak boleh.",
            "ta": "இந்த சனிக்கிழமை நான் வெளியில் இருப்பேன், அந்த நாள் வேண்டாம்.",
        },
        meaning="Excludes a specific weekday; the restriction must be preserved.",
        intent="UNSPECIFIED",
        memory=[
            {
                "key": "excluded_weekdays",
                "operation": "set",
                "scope": "future",
                "expected_status": "active",
                "value": "SATURDAY",
            }
        ],
        wait_reason="AWAITING_PATIENT_REPLY",
        tags=["timing-constraints", "excluded-weekday"],
    ),
    _scenario(
        slug="preparation-ack-02",
        stratum="preparation_acknowledgement",
        clinic_kind="doctor_instruction_check",
        clinic_turn="t1_instruction",
        step_type="INTERPRET_INSTRUCTION_CHECK",
        patient={
            "en": "Understood — and does that include water?",
            "zh": "明白了——那包括喝水吗？",
            "ms": "Faham — itu termasuk air minuman?",
            "ta": "புரிந்தது — அதில் தண்ணீரும் அடங்குமா?",
        },
        meaning="Acknowledges the instruction and adds a new preparation question.",
        intent="UNSPECIFIED",
        tasks=[
            {
                "task_type": "QUESTION",
                "outcome": "ANSWERED",
                "instruction_id": "instr-fast",
                "quote": "after midnight",
            },
            {"task_type": "PLAN", "outcome": "NOT_REQUIRED"},
        ],
        wait_reason="AWAITING_PATIENT_REPLY",
        tags=["preparation-acknowledgement", "new-question"],
    ),
    _scenario(
        slug="questions-02",
        stratum="questions",
        clinic_kind="reminder",
        clinic_turn="t1_reminder",
        step_type="REVIEW_NEEDS",
        patient={
            "en": "What should I bring with me on the day?",
            "zh": "当天我需要带什么？",
            "ms": "Apa yang perlu saya bawa pada hari itu?",
            "ta": "அன்று நான் என்ன கொண்டு வர வேண்டும்?",
        },
        meaning="Asks an answerable preparation question.",
        intent="UNSPECIFIED",
        tasks=[
            {
                "task_type": "QUESTION",
                "outcome": "ANSWERED",
                "instruction_id": "instr-prep",
                "quote": "bring your medication list",
            }
        ],
        wait_reason="AWAITING_PATIENT_REPLY",
        tags=["questions", "answered-from-source"],
    ),
    _scenario(
        slug="wrong-number-02",
        stratum="wrong_number",
        clinic_kind="reminder",
        clinic_turn="t1_reminder",
        step_type="REVIEW_NEEDS",
        patient={
            "en": "Sorry, I already told you this is not his number.",
            "zh": "抱歉，我已经说过这不是他的号码。",
            "ms": "Maaf, saya sudah beritahu ini bukan nombornya.",
            "ta": "மன்னிக்கவும், இது அவருடைய எண் இல்லை என்று சொல்லிவிட்டேன்.",
        },
        meaning="Second sender after a wrong-number flag; still not the patient.",
        intent="UNSPECIFIED",
        scored=False,
        unscored_reason="wrong_number_path_absent",
        contact_permission="stopped",
        wait_reason="CONTACT_STOPPED",
        tags=["wrong-number", "repeat-sender", "unscored"],
    ),
    _scenario(
        slug="third-party-02",
        stratum="third_party_reply",
        clinic_kind="reminder",
        clinic_turn="t1_reminder",
        step_type="REVIEW_NEEDS",
        patient={
            "en": "I'm her daughter — you can tell me the details.",
            "zh": "我是她女儿——细节可以告诉我。",
            "ms": "Saya anak perempuannya — boleh beritahu butiran kepada saya.",
            "ta": "நான் அவளுடைய மகள் — விவரங்களை என்னிடம் சொல்லலாம்.",
        },
        meaning="Third party asserts authority; authority is unverified.",
        intent="UNSPECIFIED",
        scored=False,
        unscored_reason="third_party_path_absent",
        contact_permission="unknown",
        wait_reason="AWAITING_PATIENT_REPLY",
        tags=["third-party", "asserted-authority", "unscored"],
    ),
    _scenario(
        slug="refusal-contact-stop-02",
        stratum="refusal_contact_stop",
        clinic_kind="options",
        clinic_turn="t1_options",
        step_type="REVIEW_NEEDS",
        patient={
            "en": "No, don't book that one. I'll call you back.",
            "zh": "不，不要订那个。我稍后打电话给你。",
            "ms": "Tidak, jangan tempah yang itu. Saya akan telefon balik.",
            "ta": "இல்லை, அதை பதிவு செய்ய வேண்டாம். பிறகு அழைக்கிறேன்.",
        },
        meaning="Refuses the proposed action without asking to stop contact.",
        intent="UNSPECIFIED",
        wait_reason="AWAITING_PATIENT_REPLY",
        tags=["refusal-contact-stop", "refusal-only"],
    ),
    _scenario(
        slug="ambiguous-02",
        stratum="ambiguous_short_reply",
        clinic_kind="reminder",
        clinic_turn="t1_reminder",
        step_type="CLARIFY",
        patient={
            "en": "maybe later",
            "zh": "再说吧",
            "ms": "mungkin nanti",
            "ta": "பிறகு பார்ப்போம்",
        },
        meaning="Short deferral whose meaning depends on history; requires clarification.",
        intent="UNSPECIFIED",
        wait_reason="AWAITING_PATIENT_REPLY",
        tags=["ambiguous-short-reply", "history-dependent"],
    ),
    _scenario(
        slug="switch-01",
        stratum="questions",
        clinic_kind="reminder",
        clinic_turn="t1_reminder",
        step_type="REVIEW_NEEDS",
        patient={
            "en": "What should I bring with me on the day?",
            "zh": "What should I bring with me on the day?",
            "ms": "What should I bring with me on the day?",
            "ta": "What should I bring with me on the day?",
        },
        meaning="Asks an answerable preparation question in English.",
        intent="UNSPECIFIED",
        switch={
            "turn_id": "t4",
            "step_type": "INTERPRET_INSTRUCTION_CHECK",
            "clinic_kind": "doctor_instruction_check",
            "clinic_turn": "t1_instruction",
            "patient": {
                "en": "Understood. And do I need to fast?",
                "zh": "明白了。那我需要空腹吗？",
                "ms": "Faham. Perlukah saya berpuasa?",
                "ta": "புரிந்தது. நான் உண்ணாவிரதம் இருக்க வேண்டுமா?",
            },
            "meaning": "Continues in the switched language and asks about fasting.",
        },
        wait_reason="AWAITING_PATIENT_REPLY",
        tags=["language-switch", "questions"],
        first_patient_language="en",
    ),
]


def _build_item(scenario: dict[str, Any], language: str, index: int) -> dict[str, Any]:
    slug = scenario["slug"]
    family_id = f"fam-{slug}"
    clinic_body = CLINIC[scenario["clinic_turn"]]
    switch = scenario.get("switch")
    last_patient_turn = switch["turn_id"] if switch else "t2"
    memory: list[dict[str, Any]] = []
    for entry in scenario["memory"]:
        rendered = {
            "key": entry["key"],
            "operation": entry["operation"],
            "scope": entry["scope"],
            "expected_status": entry["expected_status"],
        }
        if entry.get("language_value"):
            rendered["value"] = language
        elif entry.get("value") is not None:
            rendered["value"] = entry["value"]
        memory.append(rendered)

    tasks = [{"index": position, **task} for position, task in enumerate(scenario["tasks"])]
    checkpoint: dict[str, Any] = {
        "after_turn_id": last_patient_turn,
        "appointment_intent": scenario["intent"],
        "tasks": tasks,
        "instruction_checks": [],
        "memory": memory,
        "callback_requested": scenario["callback"],
        "delivery": {
            "expected_block": scenario["block"],
            "effective_language": language,
        },
    }
    if scenario["quote"] is not None:
        checkpoint["appointment_request_quote"] = scenario["quote"]
    if scenario["attendance"] is not None:
        checkpoint["attendance_qualification"] = scenario["attendance"]
    if scenario["wait_reason"] is not None:
        checkpoint["wait_reason"] = scenario["wait_reason"]

    fixtures: dict[str, Any] = {
        "source_api": [],
        "approved_instructions": [
            {"instruction_id": key, "approved_text": text} for key, text in APPROVED.items()
        ],
    }
    if scenario["terminal"].get("kind") == "completed_handoff":
        fixtures["staff_acceptance"] = [
            {
                "handoff_id": scenario["terminal"]["handoff_id"],
                "accepted_by": "staff-1",
                "accepted_at": "2026-09-24T09:30:00+08:00",
            }
        ]

    conversation: list[dict[str, Any]] = [
        {
            "turn_id": "t1",
            "origin": "history",
            "speaker": "clinic",
            "clinic_turn_kind": scenario["clinic_kind"],
            "body": clinic_body,
            "language_tag": "en",
        },
        {
            "turn_id": "t2",
            "origin": "replay",
            "speaker": "patient",
            "expected_step_type": scenario["step_type"],
            "body": scenario["patient"][language],
            "language_tag": scenario.get("first_patient_language") or LANGUAGE_TAG[language],
        },
    ]
    meanings = [{"turn_id": "t2", "intended_meaning": scenario["meaning"]}]
    if switch:
        conversation.extend(
            [
                {
                    "turn_id": "t3",
                    "origin": "history",
                    "speaker": "clinic",
                    "clinic_turn_kind": switch["clinic_kind"],
                    "body": CLINIC[switch["clinic_turn"]],
                    "language_tag": "en",
                },
                {
                    "turn_id": switch["turn_id"],
                    "origin": "replay",
                    "speaker": "patient",
                    "expected_step_type": switch["step_type"],
                    "body": switch["patient"][language],
                    "language_tag": LANGUAGE_TAG[language],
                },
            ]
        )
        meanings.append({"turn_id": switch["turn_id"], "intended_meaning": switch["meaning"]})

    item: dict[str, Any] = {
        "corpus_version": "1",
        "identity": {
            "family_id": family_id,
            "variant_id": f"{family_id}-{language}",
            "scenario_id": f"scn-{slug}",
            "language": language,
            "primary_stratum": scenario["stratum"],
            "tags": scenario["tags"],
            "register_markers": [],
        },
        "split": "development",
        "clock": {"reference_datetime": "2026-09-24T09:00:00+08:00", "frozen_date": "2026-09-24"},
        "environment": {
            "clinic_id": DEMO_CLINIC_ID,
            "is_demo_clinic": True,
            "patient_simulator_enabled": True,
            "translation_configured": True,
            "delivery_evidence_source": "displayed_in_simulator",
            "fixtures": fixtures,
            "translation_profile": TRANSLATION_PROFILE,
        },
        "runtime_bounds": {
            "agent_max_steps": 40,
            "role_limit_coordinator": 8,
            "role_limit_specialist": 6,
        },
        "initial_state": {
            "contact_permission": scenario["contact_permission"],
            "memory": [],
        },
        "conversation": conversation,
        "meaning_contract": {
            "intended_meaning_by_turn": meanings,
            "unresolved_ambiguity": [],
            "must_not_infer": ["must not invent availability", "must not make a source write"],
        },
        "checkpoint_oracle": [checkpoint],
        "terminal_oracle": scenario["terminal"],
        "forbidden_actions": ["booking_write", "source_write"],
        "scoring": {"scored": scenario["scored"], "unscored_reason": scenario["unscored_reason"]},
        "governance": {
            "synthetic": True,
            "pii_free": True,
            "authorship": {
                "drafter": "deepseek-v4.1-flash",
                "drafter_family": "deepseek",
                "licence": "original_synthetic",
            },
            "review": {
                "reviewer_of_record": REVIEWERS[language],
                "reviewed_at": "2026-09-24T08:00:00+08:00",
            },
            "back_translation": {
                "model": "translator-b",
                "model_family": "independent",
                "differs_from_drafter": True,
                "spot_check": {"by": REVIEWERS[language], "blind": True},
            },
            "adjudication": {"status": "unresolved", "adjudicator": None},
            "ai_declarations": [
                {"step": "drafting", "model": "deepseek-v4.1-flash", "model_family": "deepseek"}
            ],
        },
        "integrity": {
            "generation_seed": 1000 + index,
            "replay_seed": 2000 + index,
            "content_hash": "0" * 64,
        },
    }

    payload = json.dumps(
        {key: value for key, value in item.items() if key != "integrity"}, sort_keys=True
    ).encode()
    item["integrity"]["content_hash"] = hashlib.sha256(payload).hexdigest()
    return item


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "pilot": "m2",
        "families": {},
        "counts": {"families": 0, "variants": 0},
    }
    index = 0
    for scenario in SCENARIOS:
        family_rows = {}
        for language in LANGS:
            item = _build_item(scenario, language, index)
            index += 1
            path = OUT / f"{scenario['slug']}-{language}.json"
            text = json.dumps(item, ensure_ascii=False, indent=2) + "\n"
            path.write_text(text)
            family_rows[language] = {
                "variant_id": item["identity"]["variant_id"],
                "path": path.name,
                "sha256": hashlib.sha256(text.encode()).hexdigest(),
            }
        manifest["families"][f"fam-{scenario['slug']}"] = {
            "scenario_id": f"scn-{scenario['slug']}",
            "primary_stratum": scenario["stratum"],
            "split": "development",
            "variants": family_rows,
        }
    manifest["counts"] = {"families": len(SCENARIOS), "variants": len(SCENARIOS) * len(LANGS)}
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(
        f"wrote {manifest['counts']['variants']} variants across {manifest['counts']['families']} families"
    )


if __name__ == "__main__":
    main()
