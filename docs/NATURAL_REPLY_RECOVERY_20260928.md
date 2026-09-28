# Natural reply recovery — 28 September 2026

## Changes

Removed the strict prerequisite-date parser. The Coordinator now uses bounded model interpretation for natural-language answers, distinguishing an appointment preference (such as November) from the scan completion date. Saved preferences accompany subsequent clarification. Internal typed validation still checks evidence and source eligibility; patients are not required to type a fixed date format. Unknown prerequisite timing remains a reason for clinic help, not an invented date.

A routine initial synthetic reminder no longer depends on a Coordinator model call. Standalone "can" in response to that reminder is accepted as attendance intent, through the existing policy gateway. This does not mean a scan has been completed or that clinical instructions can be skipped. Mixed replies still require interpretation.

## Evidence and validation

Offline regression run: 170 passed, 16 skipped across doctor actions, scheduling, patient simulation, Bridge runtime and provider tests. Five focused regressions passed after the final prompt/contract adjustments. Ruff and formatting checks passed. Scripted models exercise natural date wording and November preference retention; this is not a fresh paid organiser-model end-to-end rehearsal.

Calvin's saved trace showed MODEL_HTTP_ERROR (HTTP 400) before the initial reminder. The provider response detail was not retained, so the exact upstream rejection cause is unknown. The routine start now avoids that unnecessary call.

## Deployment and recovery

Release: 20260928-natural-replies. Both databases backed up; all 34 tables unchanged across deployment. API and worker use identical image sha256:89e9ca30ad450171dac814b70c7f6e16df1447736eede9846f9feee7d0fccc54. All five deployed runtime files match local hashes. Public readiness returns ready.

Calvin was restarted through the authenticated fresh-simulation endpoint: waiting with one reminder, no current handoff, zero model steps. Historical failed run retained.

Priya's existing conversation was retained. A version-guarded, audited maintenance repair appended a conversational question and restored the saved November preference from her existing reply. No model result was fabricated; the recovery is explicitly labelled maintenance evidence. Her appointment is unchanged and her run is waiting for scan timing. Earlier messages remain visible as history.

All other current case summaries, source episodes/slots and WhatsApp channel state were unchanged by recovery. No patient reply was replayed and no WhatsApp message was sent. Private verification snapshots are under .cache/aws/release-20260928-natural-replies; server backups under backups/20260928-natural-replies.

No Git commit or push.
