# Clinical reply language correction — 28 September 2026

## Diagnosis

Ahmad's current run had no saved language preference. REPORT_SYMPTOMS bypassed REVIEW_NEEDS and generated a clinical acknowledgement through a response composer that defaulted to English. The clinical concern, quoted evidence and RED handoff were correct; the response language was not. The earlier Malay rehearsal used saved language preference. This is a gap exposed by reset state, not evidence that all translation was removed by the latest deployment.

## Correction

Clinical report proposals carry an optional supported reply language identified from the patient text. The reply is already bound by the existing policy to the saved patient message. Response composition uses this language when no saved preference exists; explicit preference still wins. No permanent language preference is inferred from a name or symptom report.

For a Malay clinical acknowledgement whose symptom quotes are also Malay, fixed localized callback wording preserves the exact quoted symptoms and attendance intent. It does not need a model translation call and is recorded as provider validated_template. Other translations retain existing validation and failure withholding. English source text and clinical evidence remain intact.

## Verification and limitation

110 focused tests passed across clinical review, patient memory, translations and provider before the fixed Malay-template addition. The final template change passed 15 clinical/translation tests. Ruff and formatting passed. Historical model-repair fixtures explicitly bypass the routine-reply rule to keep testing malformed model output. Chinese/Tamil translation routing was tested offline, not freshly rehearsed through the organiser model.

One live translation recovery attempt returned MODEL_SCHEMA_INVALID. Its failed result is retained in the recovery audit; no repeated paid retries were made. This organiser structured-output reliability issue remains possible for generic translations; this change does not claim to resolve its upstream cause. The fixed Malay clinical acknowledgement avoids that dependency.

## AWS and preservation

Final release 20260928-clinical-language-v2; API and worker image sha256:5251403b7e7c19946d21867e7ff8c1a11c3d17be49907f62db0bb34f114b7a1d. Four deployed files match checkout SHA-256. Both databases backed up, all 34 tables preserved across each deployment, migration heads unchanged at 0017/sim0004, public readiness 200.

Audited recovery applied the same Malay template to Ahmad's existing acknowledgement. Authenticated API verified that patient-facing body is Malay and ready. All case summaries, source episodes/slots, WhatsApp channel state, and Ahmad's run/steps/events/handoff match the pre-change snapshot. No clinical replay, source action, reset or WhatsApp send. No commit or push.

Private evidence: .cache/aws/release-20260928-clinical-language and its -v2 directory.
