# Doctor instructions and scheduling

Before a slot offer is authorized, Preparation must explicitly review every approved instruction. Each assessment carries its instruction ID and full source quote. A successful read alone is insufficient. The gateway requires complete source-matching coverage.

Claude interprets natural-language notes into one of three outcomes:

- INFORMATION: no scheduling restriction, such as bringing a booklet. Existing preparation guidance remains in effect.
- DATE_WINDOW: explicit earliest/latest dates, inclusive and interpreted in Singapore time. For example, before October 2026 ends on 30 September 2026.
- CLINIC_REVIEW: unclear anchors, conflicting instructions or conditions that cannot safely be represented by date bounds. Staff must clarify them.

Clear absolute English source boundaries (ISO dates or full month names with years) are independently calculated and intersected with the model result. This prevents a model arithmetic error such as treating “before October” as the end of October from widening the permitted window. Other wording still relies on the explicit model assessment; uncertain meanings require clinic review.

The application intersects patient preferences and all assessed doctor date windows. Excluded slots cannot be offered. If the requested slots cannot be offered within the instructions, one patient response includes the approved note, explains that a suitable time cannot be offered, and acknowledges the clinic callback request. An existing appointment remains unchanged. The normal patient-language translation and channel pipeline handles this response.

The offer records the validated Preparation decision. Booking requires that proof and a compatible slot, plus the existing source version and availability checks. Old offers without a scheduling review must be refreshed before booking. Changed doctor notes invalidate the source version and require a new offer/review; an old selection never authorizes overriding updated instructions.

This is source-grounded language interpretation followed by deterministic enforcement, not medical decision-making. The model must not infer permission to defer mandatory care. General accompaniment and preparation guidance still uses the existing question/plan flow. Ambiguous non-date scheduling requirements go to staff rather than being guessed. This does not claim that an LLM can never misinterpret a note; source-level structured restrictions would further strengthen the integration.

Validation covers in-window and out-of-window offers, Singapore midnight boundaries, missing/forged review evidence, changed doctor notes before selection, and legacy offers. Existing patient data is not rewritten; historical sent messages remain in the audit trail.

A paid live Claude test passed for a Tamil request for November against a mandatory pre-October deadline. The effective latest date was September 30, no November slot was offered, a clinic callback was requested and no appointment write occurred. Earlier validation caught and corrected both model month-boundary arithmetic and multiple requirements returned for one source note. This live test exercised interpretation and response composition against synthetic local records, not physical WhatsApp delivery.
