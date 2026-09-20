# DSPy/GEPA Spike Notes (2026-09-16)

> Origin: posted as a comment on PR #1 (`feature/live-claude-agents`, merged as `ba04de7`).
> Landed on `main` so the findings live with the merged agent runtime.
> Full experiment artifacts live in scratch dir `forget-lah-dspy/` (not committed):
> `coordinator/` holds the quote-extraction A/B (contract README, dataset, program,
> metric, both score JSONs, `AB_REPORT.md`, `mlruns-coordinator/`, `gepa_run/`);
> the root holds the Engagement slice (dataset, baseline `0.9821`, gated GEPA skeleton).

## DSPy/GEPA spike: measured prompt optimization for two agent steps (scratch-only, repo untouched)

### TL;DR
Ran an offline experiment to answer: "does prompt optimization buy us anything on the
live-Claude agent path?" Two slices, A/B measured, all work in scratch dir
(`forget-lah-dspy/` — **nothing here touches `src/`**). Headline: symptom-quote
extraction 0.64 → 0.91 with GEPA; reply interpretation already 0.98 zero-shot, left alone.

> ⚠️ **Model caveat (please read before reviewing numbers):** all scores below were
> produced on a **local Qwen 3.8-27B** (`qwen3.8-27b-ninfer` via vLLM,
> temp-0, zero-shot vs GEPA-compiled on the same dev split). They have **not** yet been
> validated against the Claude API (`claude-sonnet-4-5-20250929`, this branch's
> production provider). GEPA-optimized instructions can be model-specific — the Qwen
> gains may shrink, grow, or shift on Claude. **Recommendation is to adopt nothing
> until the Claude re-run (next step below) confirms the delta.**

### What was tested and where it sits in the pipeline

Patient message → **Coordinator (plain Python routing, untouched)** → ① symptom-quote
extractor (AI) → **verbatim-substring gateway (plain Python, untouched)** → ② reply
interpreter (AI) → **Worker (plain Python tools, untouched)**.

Only the instruction text inside boxes ① and ② was experimented on. All guardrails
(`SYMPTOM_QUOTES_NOT_IN_PATIENT_REPLY`, `ADMINISTRATIVE_TEXT_IS_NOT_SYMPTOM_EVIDENCE`,
`explicit_confirmation()` grammar) stay deterministic and were never in scope.

### Results (local Qwen 3.8-27B, seed 13)

| Slice | Dataset | Arm A zero-shot | Arm B GEPA-compiled | Δ |
|---|---|---|---|---|
| ① REPORT_SYMPTOMS quote extraction | 37 ex (26 train / 11 dev) | 0.6364 | **0.9091** | **+0.27** |
| ② Reply interpretation (option/confirmed/reason) | 45 ex (31 train / 14 dev) | **0.9821** | not run (ceiling) | — |

- ①'s misses were instruction-shaped problems GEPA is good at: framing words ("I have…"),
  trailing punctuation, admin text leaking into clinical quotes. One regression (D04) is a
  span-convention boundary, not a semantic miss. Zero post-hoc verbatim violations in both arms.
- ②'s single miss (S20: "No, I don't want any of them" → gold AMBIGUOUS_REPLY, model said
  REQUESTED_ALTERNATIVE_DATE) is a label-boundary case; no optimizer budget spent there.
- Metric in both slices is decomposable with per-predictor textual feedback (span-F1 for ①;
  0.5 selection / 0.25 confirmation / 0.25 reason for ②), tracked in MLflow.

### Method notes (for reproducibility)
- Pinned `dspy==3.3.1` + `gepa==0.1.4`; 5-arg metric contract; `dspy.GEPA(metric,
  reflection_lm, max_full_evals≤15, num_threads≤3)`; trainset/valset on `.compile`.
- Endpoint quirk found: our vLLM rejects `response_format`, so the harness degrades
  `JSONAdapter` to prompt-only structured output (verified clean; unrelated to Claude path).
- GEPA run for ①: 57 iterations / 14 candidates / ~3.5 min.

### Recommendation
- **Adopt the GEPA-compiled instructions for symptom-quote extraction (box ①) — but only
  after the Claude re-run confirms the delta.** Compiled prompt text is in
  `coordinator/gepa_run/` (`best_model.json`).
- **Keep reply interpretation (box ②) zero-shot.** Nothing to gain; don't add machinery.
- Standardize the quote span convention (perception-verb frames like "I noticed") or grow
  the dev set before shipping ①'s prompts.

### Next steps
- [ ] Re-run both arms of slice ① against the Claude API (same dataset, same seed) and
  append scores here — this is the merge gate
- [ ] If Claude delta holds: open a follow-up PR vendoring the compiled instruction text
  into `provider.py` prompts (text only — no dspy/mlflow dependency added to the app,
  per repo doctrine)
- [ ] Consider the Coordinator's remaining MEDIUM-fit surfaces only after ① ships
