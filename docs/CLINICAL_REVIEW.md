# Test a clinical symptom report

This is a local patient-message and staff-callback simulator. It does not send a real message, call a patient, diagnose symptoms or determine medical urgency.

1. Refresh the app and open Alex. Choose **Start fresh simulator test**.
2. After the reminder appears, reply: **yes, I confirm the attendance, but I have swelling in my eyes now and pain as well.**
3. Expect **RED · Staff owner needed**, with reason **Patient reported symptoms**. RED identifies a clinical review task; it is not an emergency severity classification.
4. The conversation acknowledges the symptom report and says the clinic team has been asked to call back as soon as possible. The app does not guarantee a callback time.
5. Inspect **Clinical callback**. It retains the full patient message, exact symptom quotes and any stated intention to attend. Routine booking/confirmation actions stop; stated intention is not a clinic-system confirmation receipt.
6. Select **Accept handoff as me**. The review remains open and owned. Acceptance alone does not complete it.
7. For the demo, enter a clearly fictional contact/review outcome and any follow-up. Select **Record contact and resolve review**. Only the assigned owner can do this; blank outcomes are rejected.
8. The review becomes resolved and the run completes. This records staff-reported handling, not proof that symptoms have resolved. The timeline retains the report, acknowledgement, acceptance and outcome.

## Technical behavior

Coordinator receives the full saved reply and can emit typed `REPORT_SYMPTOMS`. The decision includes the saved reply ID, exact symptom substrings, and an optional exact attendance-acceptance substring. The gateway rechecks clinic authority, request/case binding and that each quote exists in the saved message. It cannot independently establish clinical meaning or the truth of the patient's report.

The worker atomically records a `clinical_review` checkpoint, a `clinical_acknowledgement` simulated message and a `PATIENT_REPORTED_SYMPTOMS` handoff. No source booking write is needed or authorized by this action. Acceptance and resolution use authenticated staff APIs, existing clinic/CSRF/version/idempotency checks, and the named owner. They require no model calls. Existing JSON/event/message tables support the feature; no migration is needed.

Negated symptoms, resolved historical symptoms and hypothetical preparation questions should not be treated as current symptom reports. Detection is model-based and can make errors; this feature is not a clinically validated triage system. Clinical policy approval, genuine patient authentication, actual callback delivery, response-time monitoring and emergency-routing procedures remain prerequisites for real deployment.
