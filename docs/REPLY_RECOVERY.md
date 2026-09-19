# Reply evidence and staff request recovery

Patient evidence remains bound to the latest saved reply. Before validation, curly/straight single or double quotes and whitespace differences can be restored to their exact original source span. The original inbound message is never edited. The step observation records model/source quote repairs. No paraphrase, translation, word substitution, case folding or negation changes are accepted. The normal exact evidence checks run after restoration.

Claude distinguishes declining attendance from preparation difficulty using the last clinic question. A simple inability to attend requests a change and suitable dates/times, rather than becoming a clinical question. The existing doctor-note scheduling review still applies before offering or booking alternatives.

Cancellation has its own appointment intent. It creates a clinic callback task and a clear acknowledgement that the appointment is not cancelled yet. It never runs slot search or claims a source cancellation. Automatic cancellation is still unavailable; staff must act through the clinic system.

Named acceptance of a general handoff completes the agent's transfer through a policy-checked rule, without another model call that could re-escalate it. The staff task remains open. Clinical reviews and callbacks remain owned and unresolved until staff explicitly resolves them; accepting them does not finish those tasks.

When a case is awaiting staff, WhatsApp acknowledgements distinguish unassigned requests from accepted requests and retain the latest message for staff review. Cancellation status remains explicitly pending. No callback time or appointment change is invented.
