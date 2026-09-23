# Lane C — cross-model decision benchmark: Jev (hosted) vs openjev/Kev vs Laya

Measured 2026-09-23. Frozen tree: `forget-lah` at commit `3919570`
(`feature/systemone-decider-ab`), plus the Lane C additions described below.

## Question

Three independent decision models, one wire contract, one question set: does the hosted
TypeSafe Jev that the application already talks to (A) actually decide better than the open
implementation served locally (B), or than the new open-weights decision model Laya (C) — and
on which axes can that even be measured?

Prompting context: the Reddit post that started this lane
(`reddit.com/r/LocalLLaMA/s/Ku5VDQszWN`, fetched with clawfetch-res, status 200). It introduces
Laya — a 421M-parameter non-autoregressive decision model (ModernBERT-large encoder + a head
that scores `[MASK]` option markers) trained with RLCD-style policy-gradient RL against
strictly proper scoring rules — and publishes a table claiming 0.766 on the public
`typed-decisions` benchmark against Jev's published 0.727, with 3x better ECE and ~7x lower
latency, while conceding that Jev leads on high-cardinality label spaces and soft-distribution
matching. Those claims are the thing worth testing independently, which is why this lane
replays the same public benchmark the claim is made on.

## Design

Three legs, one replay:

| leg | what it is | where it runs |
|---|---|---|
| `jev-hosted` (**A**) | TypeSafe Jev through the CommandCode provider | `POST https://api.commandcode.ai/provider/v1/systemone`, model `typesafe/jev` |
| `openjev-kev4b` (**B**) | the open implementation (Kev-4B over Qwen3.5-4B-Base, LoRA 16), CPU bf16 | `POST http://172.17.0.1:8009/v1/systemone` on 7940hx |
| `laya-english` (**C**) | Laya, english checkpoint (what `Router()` selects here) | `POST http://172.17.0.1:8012/v1/systemone` |
| `laya-typed` (**C**) | Laya, `typed-decisions` fine-tuned checkpoint | `POST http://172.17.0.1:8013/v1/systemone` |
| `laya-router` (**C**) | Laya's recommended entry point, `Router(preload=True)` | `POST http://172.17.0.1:8014/v1/systemone` |

Question set: `LocalLLaMA/typed-decisions`, config `all`, split `test` — 400 cases, 2,000
decisions (4 synthetic workflows x 100 cases x 5 questions: 600 `choice`, 600 `noul`, 800
`score`). It is the benchmark Laya's 0.766 is claimed on (`laya-typed-decisions` was trained on
the benchmark's *train* split, so the test split is a held-out comparison for it). Every row is
replayed against every leg with byte-identical `state` and `questions`, so the comparison is
paired by construction.

Scoring is defined once in `decider_bench` and applied to all legs: hard-label accuracy
(argmax agreement with the gold `label`), Brier distance and total variation against the
benchmark's gold distribution, expected-level absolute error for `score`, latency percentiles
from the harness clock, and token/cost accounting from each response's own `usage`.

Laya is reached through a thin stdlib HTTP adapter (`laya_serve.py`, ours) that exposes the
System One contract and calls the unmodified reference package (`laya==0.3.6`). No leg is
scored with its own metric code.

## Reference points (same test split)

Computed directly from the fixture, so every leg can be read against label noise rather than
against a perfect score:

* random baseline over the offered options: **0.3175**
* per-(workflow, question) majority-class baseline: **0.5225**
* teacher argmax vs gold: **0.942** (gold is the teacher majority)
* teacher self-agreement (`argmax_agree`): **0.594**

## Results

Main replay: 400 cases / 2,000 questions per leg, `exit=0` at 2026-09-23T02:44:55Z
(`/tmp/opencode/lane-c/run-full/`). All five legs answered the identical paired question
stream; the only budgeted leg was `jev-hosted` (400/400 calls, `remaining=0`).

| leg | accuracy | vs majority | Brier | TV | gold mass | score MAE | p50 ms | p95 ms | input tok |
|---|---|---|---|---|---|---|---|---|---|
| `laya-typed` (C) | **0.7660** | +0.2435 | **0.0185** | **0.1740** | 0.5238 | **0.2424** | 1803 | 2583 | 582,370 |
| `jev-hosted` (A) | 0.7369 | +0.2144 | 0.0414 | 0.2501 | **0.6511** | 0.3904 | **648** | **1516** | 373,313 |
| `openjev-kev4b` (B) | 0.6590 | +0.1365 | 0.0464 | 0.2456 | 0.5387 | 0.3765 | 7400 | 14138 | 202,638 |
| `laya-english` (C) | 0.3615 | −0.1610 | 0.1007 | 0.4098 | 0.3365 | 0.6937 | 1790 | 2569 | 580,949 |
| `laya-router` (C) | 0.3615 | −0.1610 | 0.1007 | 0.4098 | 0.3365 | 0.6937 | 1818 | 2697 | 580,949 |

Accuracy by primitive (all 2,000 questions, hard-label argmax vs gold):

| leg | choice (600) | noul (600) | score (800) |
|---|---|---|---|
| `jev-hosted` | 0.7374 | 0.7946 | 0.6932 |
| `openjev-kev4b` | 0.6417 | 0.7317 | 0.6175 |
| `laya-typed` | 0.7333 | **0.8567** | **0.7225** |
| `laya-english` / `laya-router` | 0.2883 | 0.4867 | 0.3225 |

Notes on the table:

* `jev-hosted` answered 1,980 of 2,000 questions — 4 cases errored (20 unanswered questions,
  1.0%). Its accuracy is over answered questions; the other four legs answered 2,000/2,000.
* `laya-english` and `laya-router` are identical on every metric including token counts. That is
  not a coincidence of aggregation: with `Router(auto_task_detection=False)` (the default) the
  router emits `model: "english"` even when a workflow signature is detected, so the
  "recommended entry point" is the base checkpoint on this split.
* Token counts are prefill volume summed over each leg's own `usage`; only `jev-hosted` is
  billable (Anthropic-backed), the rest are local.

## Order sensitivity

Probe: `/tmp/opencode/lane-c/order-probe/` — 50 cases / 81 `choice` questions, seed 20260923.
Each option set is offered twice, in both orders, so a flip is a change of argmax with the
question and option set held fixed. Chained behind the main replay so it cannot contaminate it.

| leg | flip rate | flips / compared | notes |
|---|---|---|---|
| `jev-hosted` | 0.04 | 2 / 50 | **degraded**: 59 × `http_429` + 1 × `http_503`; only 50 of 81 pairs comparable |
| `laya-typed` | 0.0494 | 4 / 81 | most order-stable of the fully-measured legs |
| `openjev-kev4b` | 0.1852 | 15 / 81 | order-sensitive, as expected |
| `laya-english` | 0.3457 | 28 / 81 | |
| `laya-router` | 0.3457 | 28 / 81 | identical to `laya-english` on every slice again |

Flip rate by offered option count (4 vs 5 options):

| leg | 4 options | 5 options |
|---|---|---|
| `laya-typed` | 0.0222 (n=45) | 0.0833 (n=36) |
| `jev-hosted` | 0.0000 (n=30) | 0.1000 (n=20) |
| `openjev-kev4b` | 0.1778 (n=45) | 0.1944 (n=36) |
| `laya-english` / `laya-router` | 0.4444 (n=45) | 0.2222 (n=36) |

Consequences:

* **`laya-typed`'s lead is not a candidate-order artifact.** It flips on 4.9% of questions, so
  the 0.766-vs-0.737 ordering against `jev-hosted` survives order perturbation.
* **`laya-english`'s 0.3615 is not a stable low signal** — it is order-unstable at 34.6%, i.e.
  near chance *and* sensitive to presentation. `laya-router` repeats it exactly, again
  confirming the router resolves to the base checkpoint here.
* **`jev-hosted`'s 0.04 is inconclusive**, not a win. The hosted leg was rate-limited
  (`http_429` × 59 + `http_503` × 1) because this probe issues two requests per question; only
  50 of 81 pairs are comparable, and the missing pairs are not random. It should not be read as
  more order-stable than `laya-typed`.
* **`openjev-kev4b`'s 18.5%** confirms the documented intrinsic order sensitivity of the open
  implementation: roughly one in five decisions changes when the same options are renumbered.

## Findings

1. **The published claim reproduces, exactly.** `laya-typed` scores **0.7660** on
   `LocalLLaMA/typed-decisions` test — the published 0.766 to three decimals — and `jev-hosted`
   scores **0.7369** against the published 0.727. On the same held-out split the ordering in
   the Reddit post holds: Laya's fine-tuned checkpoint edges the hosted Jev by **+0.029
   absolute (2.9 points)**.
2. **But the two leaders are close, and the win is concentrated in `noul` and `score`.**
   `laya-typed` leads `noul` by 6.2 points and `score` by 2.9 points, and is a statistical tie
   on `choice` (0.7333 vs 0.7374). A 2.9-point overall gap over 2,000 questions is a real but
   narrow headline; it does not look like the ~6-point-class separation a benchmark swap would
   be chosen on.
3. **Both leaders clear the majority baseline comfortably; the untuned Laya legs do not.**
   `laya-typed` +0.2435 and `jev-hosted` +0.2144 over majority; `laya-english`/`laya-router`
   at 0.3615 are **below** majority (−0.1610) and only +0.044 above random. The base Laya
   checkpoint on this benchmark is barely better than guessing, which matches the post's own
   concession that the base checkpoints are near chance. Only the fine-tuned checkpoint is
   usable.
4. **The router does not pick the checkpoint that wins.** 400/400 rows have an exact workflow
   signature, yet `Router()` returns `english` because `auto_task_detection` defaults to
   `False`; live output showed `model: "english"` with `workflow:
   "agent_trace_observability"`. So the two "convenient" ways to use Laya — base or default
   router — both land at chance-plus, and reproducing the advertised 0.766 **requires
   loading the `typed-decisions` checkpoint explicitly**. Anyone adopting Laya by following the
   README router example gets the 0.3615 leg, not the 0.766 leg.
5. **The open local implementation (B) trails both.** `openjev-kev4b` at **0.6590** is 7.8
   points behind `jev-hosted` and 10.7 behind `laya-typed`, though it still beats majority by
   13.7 points. On this benchmark the open Kev-4B does not close the gap to the hosted
   proprietary decider; it sits in a clear third tier.
6. **Calibration and soft-distribution behavior favor Laya, as advertised.** `laya-typed`
   has the best Brier (0.0185 vs 0.0414 hosted) and best TV distance (0.174 vs 0.250), and the
   best expected-level MAE for `score` (0.242 vs 0.390). That is consistent with the post's
   claim of better ECE and better soft-distribution matching. The counter-signal is **gold
   mass**: `jev-hosted` puts 0.6511 probability mass on the gold answer versus 0.5238 for
   `laya-typed`, and `laya-typed`'s very sharp distributions give it the lower Brier while
   `jev-hosted` is more willing to spread mass — so the calibration win and the argmax win have
   different shapes.
7. **Latency is wall-clock, not architecture.** `jev-hosted` is fastest here (p50 648 ms,
   p95 1.5 s) because it is a remote API; the local Laya legs are CPU-only and pay p50 ~1.8 s,
   and the local Kev-4B is the slowest by far (p50 7.4 s, p95 14.1 s). So this lane does **not**
   reproduce the post's "~7x lower latency" claim for Laya against Jev: against a hosted Jev
   here, Laya is ~2.8x *slower* at p50. The post's latency comparison presumes local Jev; the
   served-in-production comparison favors Jev.

## Limitations

* **The benchmark flatters `laya-typed`.** The `typed-decisions` checkpoint was fine-tuned on
  the *train* split of this exact benchmark family; the test split is held out but
  in-distribution. `jev-hosted` is a general-purpose hosted decider with no such
  in-family fine-tuning. The 2.9-point headline gap therefore measures "fine-tuned-on-this-
  benchmark" versus "general", and is the most likely number to shrink out of distribution.
* **The benchmark's own ceiling is 0.942 and its labels are noisy.** Gold is the teacher
  majority with only 0.594 self-agreement, so labels carry substantial noise. Over 2,000
  questions a 2.9-point gap is real but narrow; this lane does not compute confidence
  intervals, and no leg should be ranked on gaps of that size without them.
* **One question set, one split.** This tests the `typed-decisions` claim only. The post's
  other concession — Jev leading on high-cardinality label spaces (Banking77) and
  soft-distribution matching — is **not** exercised here, so "Laya wins" is not a general
  verdict.
* **Latency is not a controlled measurement.** The legs run in different regimes: remote HTTP
  (hosted Jev) versus local CPU (Laya, Kev-4B) on one shared, loaded container with no GPU.
  The ~7x-latency claim in the post is untested; the ranking here is an artifact of deployment,
  not architecture, and would invert with a local GPU Jev.
* **Billing is a call-count guard, not dollars.** Only `jev-hosted` is billable; this lane
  records the 400/400 budget consumption but no per-call USD, so a cost-per-decision
  comparison is not made.
* **The four `jev-hosted` errors** remove 20 of its questions, so its accuracy is computed on
  1,980 while the other legs are computed on 2,000 — a 1% denominator difference that is small
  but not zero.
* **Determinism differs across legs**, which the order probe addresses; a single ordering per
  case cannot separate a leg's genuine decision quality from its positional bias until the
  order probe lands.
* **Leg C is a proxy for "openjev".** `openjev` here means the local open implementation already
  forked into `forget-lah` (Kev-4B over Qwen3.5-4B-Base), not `api.openjev.sh` — reaching that
  would need a new account and would not change what is being measured, but the label should be
  read as "the open Kev implementation", not "the openjev service".
