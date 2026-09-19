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
