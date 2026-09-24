# Reply evidence and staff request recovery

Patient evidence remains bound to the latest saved reply. Before validation, curly/straight single or double quotes and whitespace differences can be restored to their exact original source span. The original inbound message is never edited. The step observation records model/source quote repairs. No paraphrase, translation, word substitution, case folding or negation changes are accepted. The normal exact evidence checks run after restoration.

Claude distinguishes declining attendance from preparation difficulty using the last clinic question. A simple inability to attend requests a change and searches available alternatives, rather than becoming a clinical question or requiring the patient to invent suitable dates before seeing options. The existing doctor-note scheduling review still applies before offering or booking alternatives.

Cancellation has its own appointment intent. It creates a clinic callback task and a clear acknowledgement that the appointment is not cancelled yet. It never runs slot search or claims a source cancellation. Automatic cancellation is still unavailable; staff must act through the clinic system.

Named acceptance of a general handoff completes the agent's transfer through a policy-checked rule, without another model call that could re-escalate it. The staff task remains open. Clinical reviews and callbacks remain owned and unresolved until staff explicitly resolves them; accepting them does not finish those tasks.

When a case is awaiting staff, WhatsApp acknowledgements distinguish unassigned requests from accepted requests and retain the latest message for staff review. Cancellation status remains explicitly pending. No callback time or appointment change is invented.

## Availability requests and conversation progress

The September 19 Priya trace showed three replies (attendance refusal, request for available slots, repeated request) each becoming a generic timing clarification. The earlier prompt incorrectly treated missing preferences as missing required information. Single-turn tests did not catch this conversation regression.

Scheduling preferences are optional search filters. A CHANGE assessment with CLARIFY_TIME, no explicit ambiguity and no preparation issue is corrected to SEARCH_SLOTS by application policy. The original model decision remains in the trace; the observation records OPTIONAL_PREFERENCES_DO_NOT_BLOCK_SEARCH and the checkpoint records the effective action. No patient-word dictionary is used for this correction. A specific unclear date or unusable stated preference requires a typed clarification_reason and a focused question. Doctor-note review, saved restrictions, source freshness and consent checks still apply. The existing appointment time is excluded from alternatives when rescheduling.

The step allowance is bounded per new patient reply (40 maximum), while cumulative step history remains visible. A new authenticated simulator event or deduplicated WhatsApp reply starts an allowance; staff retry/pause retains it. Per-role limits, provider pacing and the shared daily paid-call cap are unchanged. Waiting consumes no model calls. This avoids pausing a legitimate longer conversation because earlier completed turns consumed its total step allowance.

Offline regression coverage replays the faulty null-clarification proposals over three patient turns, then books only after explicit selection. It also covers doctor deadlines, exclusion of the current appointment, genuine date ambiguity and inability to reset an exhausted reply budget by retrying. Tamil and Malay fixtures test Unicode evidence and orchestration with supplied semantic decisions; they do not prove live model language accuracy. No paid inference or patient-message replay is part of this validation.

Instruction-check `answer_quote` now participates in the same source-span restoration. Regression coverage uses the September 23 Priya failure: a straight apostrophe in the model quote is restored to the saved curly apostrophe and the workflow offers alternatives without booking. An invented completion statement is still denied; patient text is unchanged.

## Preserve understood confirmation before preparation review

After a policy-accepted REVIEW_NEEDS classifies the latest reply as an unqualified CONFIRM, the coordinator deterministically delegates the required Preparation review. A second model call cannot contradict that same saved interpretation by asking attendance again before reading the doctor's instructions. This is semantic-state routing, not a dictionary for the word `can`, and does not authorize a source write.

The rule requires the matching latest patient reply and successful needs-review step, skips questions, concerns, comprehension requests and attendance qualifications, and preserves the ordinary delegation policy. Existing pending instruction checks and completed Preparation reviews retain their paths. The step records rule provenance and the needs-step/reply evidence IDs. Offline coverage supplies equivalent confirmed intents across four phrases/languages; it tests workflow behavior, not live language understanding.

## Scheduling constraints inside a failed prerequisite answer

A rich NOT_MET answer to a doctor-instruction check remains the active patient reply for scheduling assessment. Its scan dates and requested timing must not be discarded by restoring the earlier attendance reply and manufacturing an unrestricted search. The resolved clinic consequence and source instruction evidence remain attached; the coordinator must assess the full answer's constraints before delegation or offering options. The policy gateway denies bypassing this phase. Plain closed yes/no answers continue to resume their parent protocol turn.

Date bounds can be open-ended: after a specified day uses the following day as an inclusive lower bound, with no invented upper bound. Invalid/reversed bounds and conflicting requested dates remain rejected. Regression coverage exercises before/on/after boundary options, no eligible slots, a changed source slot before selection, bypass rejection, and explicit selection through one source booking. It uses supplied semantic model decisions and makes no paid model calls.

## WhatsApp instruction-check continuity (23 September)

The WhatsApp inbound handler discarded `instruction_check_resolutions` when rebuilding the next-turn checkpoint. The staff simulator retained them, so simulator-only tests missed the live failure. If Preparation ran before Engagement interpreted a slot selection, the answered scan question was asked again. WhatsApp now preserves the same source-bound resolutions; changed doctor-note text still invalidates prior evidence. No answer is inferred from appointment acceptance.

Offline tests now exercise channel ingestion as well as the staff API for rich scan answers, date filtering, unavailable/changed slots and selection. A supplied-decision replay of `10th oct works for me` forces the observed Preparation-first order. Removing only the channel fix reproduces the failed waiting state; retaining it permits the existing source-checked booking path. These are orchestration tests, not paid live-language validation. Existing damaged conversations are not automatically repaired, restarted or replayed.

## Conversational continuation and practical-plan conflicts

REVIEW_NEEDS now distinguishes ACTION, ACKNOWLEDGEMENT and GREETING. Social-only proposals cannot also contain appointment actions, questions, plans, preferences or concerns. A purely social reply is acknowledged without specialist review or appointment writes; a completed case's continuation ends with CONVERSATION_ACKNOWLEDGED. Independent cancellation remains an owned-staff-request path, never an automatic cancellation claim. Needs review is also available while a doctor check is pending, so thanks and cancellation are not forced into a prerequisite answer. Current symptoms retain REPORT_SYMPTOMS.

Validated Preparation CONFLICTS/POSSIBLE_SUBSTITUTION results now pause before attendance writes. The pending source-bound issue survives WhatsApp and staff replies, including social acknowledgements and plain attendance acceptance. A fresh SATISFIES assessment for the same quoted instruction clears it; requests for clinic help retain the callback path. The write gate independently rejects pending conflicts. An already validated, compatible CONFIRM intent is reused rather than asking Engagement to reinterpret the same consent and potentially repeat the attendance question.

Patient-message translation explicitly includes quoted instructions. Confirmation messages omit raw notes classified as staff patient-check protocols or matching saved check resolutions; the complete originals remain in Doctor notes. Mixed notes containing both staff checks and informational text are conservatively withheld as a whole from the automatic confirmation, rather than paraphrased into invented patient guidance.

Validation is 14 new offline tests through channel ingestion and the staff API, including conflict/thanks/plain-confirmation/compatible-plan progression, multilingual social replies after completion, cancellation during a scan check and after completion, mixed thanks plus symptoms, no raw scan-protocol dump, and the quoted-instruction translation contract. These use supplied semantic decisions and mock translation responses; no paid language-model replay was performed. Per user instruction, the full regression suite is being run separately by the user and is not claimed as passed for this release.

## Follow-up correction: truncated warning and compatible-plan continuation

The next Alex take saved a complete English warning but a Chinese translation consisting only of a label. Numeric-preservation validation did not detect this because the warning contained no digits. Translation now rejects gross truncation (for sources at least 100 characters, output must be at least 12 characters and 10 percent of source length), allowing one budgeted retry before failure; failed text is not eligible for channel delivery. This is a truncation safeguard, not proof of semantic completeness or translation accuracy.

The accompaniment reply was correctly classified as a new plan with UNSPECIFIED appointment intent, but the coordinator attempted an invalid barrier assessment. Pending plan tasks now deterministically delegate to Preparation through policy. Once the instruction is satisfied, a previously validated confirmation can resume for the same scheduled time, with original reply evidence and the new Preparation resolution retained. Changed appointment time requires new confirmation. Seven new offline tests cover the saved failure patterns, bounded retry, unchanged-time continuation and changed-time refusal. Historical messages and paused cases are not repaired or replayed automatically.


## Complete translation sections (23 September)

The fresh Alex run reached AWAITING_COMPATIBLE_PLAN with a complete source warning, but both translation attempts failed validation. No warning was delivered. The exact rejected provider outputs were not retained, so the cause of this latest rejection is not proven. Long, multi-section messages now request a required output field per sentence/paragraph section in one provider call. Each field is validated for presence, gross truncation and numeric preservation before reassembly; source separators remain unchanged. Mixed-language spans must all be translated or retained as appropriate, without omitting the surrounding message. Short messages retain the prior contract. This improves coverage enforcement; it does not prove semantic translation accuracy or eliminate provider failures.

Nine new offline HTTP-mock tests pass, including the Chinese driving warning, missing/blank/label/wrong-type sections, swapped dates, short-message compatibility and trailing whitespace. No paid inference was used. The existing failed message is not reset or resent automatically. Full regression remains assigned to the user.
