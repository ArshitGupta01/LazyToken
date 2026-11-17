# Mobile prompts and mode benchmarks

The PC application is still the local repository index and graph. Phones use a
separate presentation of the same product: a lightweight prompt hub, without a
graph, chat backend or API keys in the browser.

## Audit and scope

The existing application uses Python's standard library, SQLite, vanilla JavaScript
and CSS. The hosted `web/` landing page detects the desktop loopback service and
opens its private dashboard. It is not an AI chat application. Existing benchmark
modules evaluate repository retrieval or manually captured coding runs, rather
than Normal/Lite/Pro prompt behavior.

The original product brief defined Lite/Pro behavior and benchmarking requirements;
it does not supply complete Lite/Pro prompts. No prior implementation of those
modes was found. `web/prompts.json` therefore defines version 1.0.0, authored from
those requirements, plus the agreed reuse-first Coding prompt. This is the single
source for both the browser's copy buttons and the benchmark runner. The prompts
are not silently replaced with shorter benchmark-only variants.

## Mobile experience

- `web/mobile.html`: three prompt cards, prompt previews, one Copy button per mode,
  How to use, and a mobile benchmark report viewer.
- `web/mobile.css`: reuses `web/styles.css` colors, typography, cards, pills and
  launch buttons; adds the mobile layout, safe-area navigation and charts.
- `web/mobile.js`: loads the canonical prompts, copies the exact text, selects text
  for manual copy when clipboard permission is unavailable, and manages report
  import/export and local browser history.
- `web/prompt-metrics.js`: validates imported runs and calculates matched-trial
  comparisons from stored raw data. It never supplies demonstration measurements.
- `web/app.js`: phones and iPads route to `mobile.html` without polling loopback.
  Desktop routing remains the existing local-dashboard flow. `?desktop=1` bypasses
  mobile routing when a user explicitly chooses PC setup.

Use: choose Lite, Pro or Coding, tap Copy prompt, paste it into an AI assistant,
then send the task. Coding users attach relevant files and describe their stack
in that assistant. The mobile site makes no model calls. Pasting a prompt cannot
enforce model behavior, grant repository access, or guarantee token savings.

## Preview and deploy

From the repository, with an installed Python interpreter:

```powershell
python -m http.server 8877 --bind 127.0.0.1 --directory web
```

Open `http://127.0.0.1:8877/mobile.html`. Desktop visitors to the root page keep the
existing setup flow. Deploy the existing `web/` static directory with its current
hosting workflow; no new hosting account or backend is required. This change does
not publish or push the repository automatically.

## Benchmark protocol

The new runner is `benchmark/prompt_modes.py`, also exposed as
`python kn.py prompt-benchmark`. It uses the standard-library HTTP client and the
official OpenAI Chat Completions endpoint. No provider SDK was added. The existing
`python kn.py benchmark` retrieval benchmark is unchanged.

The default suite contains three cases in each of twelve categories: general
knowledge, everyday conversation, current-research abstention, website development,
debugging, long-document summaries, reasoning, multi-step instructions, context
retention, hallucination prevention, image prompt consent, and conversation
compression.

Normal has no TokSmart instruction. Lite and Pro use the exact copied text. The
instruction is sent as a **user message**, matching mobile copy/paste, rather than
being elevated to a system instruction. Cases share the same initial context,
task, model, generation settings and tool access. Each case defaults to three
trials, with reproducible randomized mode order. An optional Coding arm is stored
and exported but is not pooled into the required Normal/Lite/Pro charts.

```powershell
# Offline preview. No credentials, database creation or model calls.
python kn.py prompt-benchmark plan

# Small experiment before spending on the full suite.
# Configure OPENAI_API_KEY securely in your local environment first.
python kn.py prompt-benchmark plan --category programming_debugging --trials 3
python kn.py prompt-benchmark run --model YOUR_MODEL --category programming_debugging --trials 3 --confirm-calls 27

# Full experiment: 324 runs / 342 calls. Provider charges may apply.
python kn.py prompt-benchmark run --model YOUR_MODEL --confirm-calls 342

# Optional Coding arm, or a single case.
python kn.py prompt-benchmark run --model YOUR_MODEL --include-coding --case website_development-1 --confirm-calls 12

# Export a selected experiment printed by the run command. Files must be new.
python kn.py prompt-benchmark export results.json --experiment EXPERIMENT_ID
python kn.py prompt-benchmark export results.csv --experiment EXPERIMENT_ID --format csv
```

Use the same model with support for the chosen settings in every arm. Unsupported
settings are recorded as failures; the runner does not silently change settings.
It stops on request, authentication, access and rate-limit failures, saving runs
already completed. There are no automatic paid retries. A subsequent invocation
creates a new experiment and preserves history.

Provider-reported prompt, completion and total counts include instruction overhead
and repeated multi-turn context. Each response's raw usage is retained. Missing or
inconsistent usage remains unknown and is excluded from savings, rather than
replaced by fabricated measurements. Instruction-only size is separately labeled
as a characters/4 estimate; it is already part of provider input counts and is not
added again. Exact context-only tokens are unavailable and remain null. The runner
supplies no tools, so tool-token overhead is zero.

Optional pricing flags accept user-supplied USD rates per million tokens:
`--input-usd-per-million`, `--output-usd-per-million`, and
`--cached-input-usd-per-million`. Without rates, cost is unknown. If no cached rate
is supplied, cached input uses the regular input rate. Costs are labeled estimates,
not invoices. Update pricing yourself; there are no hardcoded model prices.

## Quality evaluation and corrections

Every run starts **unscored**. The six criteria are accuracy, completeness,
relevance, clarity, instruction following and practical usefulness, each 0–10.
Scores are not inferred from response length.

```powershell
python kn.py prompt-benchmark score RUN_ID --scores '{"accuracy":8,"completeness":8,"relevance":9,"clarity":8,"instruction_following":9,"usefulness":8}' --notes 'Manual review against the case checklist'

# Optional paid, blind evaluation using a different model.
python kn.py prompt-benchmark judge --experiment EXPERIMENT_ID --model DIFFERENT_EVALUATOR_MODEL
```

The AI evaluator receives the task, supplied context, checklist and response. It
does not receive the mode or optimization instruction. Evaluation order is
randomized. AI scores are labeled AI evaluations; manual scores and later
corrections preserve evaluation history. Different evaluator kinds or IDs are not
mixed inside a quality comparison. Evaluator model billing is separate from the
generation-token comparison; it is not currently included in the cost charts.

Current-news cases test honest abstention because every arm lacks browsing. They
do **not** establish live research quality. Image cases are text-only and include
fixed follow-up consent/refusal turns. Judge notes record consent behavior; there
is no image generation or claim about actual image quality. Multi-turn context
cases use supplied histories and include repeated prompt tokens in billing totals.
There is no autonomous compaction or coding-tool execution in this runner, so it
does not establish end-to-end coding-agent savings.

Custom cases are a JSON array. Every case needs `id`, `category`, `task` and
`expected`; optional `context` contains user/assistant messages, and `followups`
contains subsequent user messages. Use the global argument before the command:

```powershell
python kn.py prompt-benchmark --cases custom-cases.json plan
python kn.py prompt-benchmark --cases custom-cases.json run --model YOUR_MODEL --confirm-calls COUNT_FROM_PLAN
```

## Storage and mobile results

Runs persist in an additive `prompt_mode_runs` table in the TokSmart
SQLite database. `--db PATH` before the command selects a separate database.
Responses, tasks, exact instructions, hashes, version, trial, model, settings,
timestamps, usage, timing, evaluation notes and failures are retained. API keys
are read only from the environment and never stored in records or exports.

Import the exported JSON in the mobile Benchmarks section. History is merged by
run ID and survives refresh in the same browser. Changed records are rejected
instead of overwriting silently; export then clear with confirmation before
importing corrected scores. Browser-storage failure is reported without changing
history. Reports can contain task text: treat them as private data.

Charts are calculated from raw imported runs. Only complete successful
Normal/Lite/Pro trials with provider usage and identical task/context/settings,
model, provider, tool access, experiment and prompt version are compared. Prompt
hashes must be stable within an experiment. Quality and cost comparisons use only
trials where all three corresponding values are known. Unknowns and zero
denominators remain unknown. Input/output/total tokens, timing, quality, cost,
token savings, quality differences and cost savings appear per compatible group.
Quality-qualified lowest-token mode is descriptive, not a statistical claim.

The mobile page filters reports by category, provides per-run response details,
and exports JSON/CSV. It runs no paid experiments from the phone; those are
explicit CLI commands on the computer. Report values are imported evidence, not
cryptographically authenticated provider records. Clear browser history requires
confirmation. Deleting a computer experiment separately requires its ID twice:

```powershell
python kn.py prompt-benchmark reset --experiment EXPERIMENT_ID --confirm EXPERIMENT_ID
```

## Verification and honest limits — 2026-11-16

Executed offline: canonical prompt-copy tests; clipboard denial; loading failure;
mobile routing; desktop connection regressions; report persistence, exports and
reset confirmation; matched-token and quality calculations; model/settings/tool/
context mismatch exclusion; zero denominators; randomized plans; multi-turn usage;
failure/truncation handling; SQLite persistence; score corrections; exclusive
exports; and missing-key refusal. Synthetic provider fixtures exist only in tests
and temporary test databases. They are not published benchmark results.

The dry plan validates 36 cases, 12 categories, three trials, 324 runs and 342
model calls. A live-run attempt exits before any API call because no
`OPENAI_API_KEY` is configured in this environment. **No live token savings,
quality improvement or best-performing mode has been measured.**

The mobile prompt and benchmark screens were visually checked at a 390 × 844 browser
viewport. The duplicate native file picker was removed from the benchmark import
control. Physical Android/iOS devices, clipboard permission behavior and every
responsive width have not been checked. No new dependencies were added.

Executed check results:

| Check | Result |
| --- | --- |
| JavaScript checks | 21 passed |
| Prompt-runner unit checks | 11 passed |
| Staged npm 0.5.2 CLI | Doctor and offline plan passed |
| Full Python unit suite | 295 run: 290 passed, 5 skipped |
| Existing E2E suite | 209 passed |
| Python formatting | Black passed for changed Python files |

No live provider benchmark was run, so the site shows no measured savings.
