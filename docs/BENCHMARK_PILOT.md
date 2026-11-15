# Authorized real-agent pilot — November 15, 2026

## Larger source-tree, preloaded-context experiment

Two matched pairs used isolated copies of LazyToken's Python source and tests, with the same deliberately reintroduced session-checkpoint bug and task. The copied fixture omitted non-Python application assets. A small approved/verified **synthetic fixture lesson** identified the relevant module and database table; it simulated a reviewed memory and was not a human review of production knowledge. Only the brief arm received that lesson in its initial prompt through `context --prompt --expand-assets --budget 350`. Neither arm had an MCP server. Both agents ran the targeted broker tests; independent checks also verified ordering, the 30-key limit, ties, empty sessions and scope. All four runs passed. The starting bug was separately confirmed to fail the independent checks, and the known fix passed them.

| Pair and order | Baseline total | Brief total | Difference | Baseline cached input | Brief cached input |
| --- | ---: | ---: | ---: | ---: | ---: |
| Baseline first | 122,884 | 121,086 | −1,798 (−1.46%) | 108,928 | 100,224 |
| Brief first | 161,101 | 142,117 | −18,984 (−11.78%) | 124,800 | 129,024 |
| Combined | 283,985 | 263,203 | −20,782 (−7.32%) | 233,728 | 229,248 |

Totals are provider-reported input plus output; cached input is already included in input. Uncached input summed to 46,196 for baseline and 31,306 with the brief. Baseline agent times were 55.032 and 58.204 seconds; brief agent times were 38.406 and 51.234 seconds, plus 0.562 and 0.578 seconds of local indexing and brief preparation. Indexing made no model calls. The harness also indexed the baseline fixture during setup, but that index was not supplied to the baseline agent. Dollar cost, unnecessary reads and retry counts were not independently measured.

The two pairs concern one deliberately constructed task, one model and one source snapshot (`sha256:b897beceb736b90bc9c708fff01da96f3805bf6d5561efdbc3b1893c4e80a053`), with a pre-seeded synthetic lesson and one observation per arm per pair. They show the brief was useful to test, not that LazyToken reliably saves tokens or that MCP retrieval caused savings. Raw records and traces remain in the local workspace under `work/repo-prefetch-pilot-20261115` and `work/repo-prefetch-pilot-reversed-20261115`.

After those runs, `context --prompt` was changed to omit bookkeeping that an agent does not need while retaining project scope, budget type, results, truncation and session-suppression indicators. Re-encoding the first pair's saved brief with the revised shape reduced its character-based JSON estimate from 336 to 268 tokens. This is an offline estimate of that one context payload, not a provider measurement or a new agent benchmark. The CLI checks the selected token counter and falls back to the original bounded payload if the smaller JSON would tokenize above the limit.

## Repeat after MCP and context changes

An additional isolated multi-file follow-up compared a baseline against LazyToken with an approved, verified session-expiry lesson. Both runs passed their existing and independent acceptance checks. The baseline used 63,093 tokens (62,252 input, 841 output); LazyToken used 62,765 (62,107 input, 658 output), a 328-token reduction. Cached input was 44,544 and 48,512 respectively. Each condition ran once in that order; LazyToken made no MCP calls, so this does not establish a graph benefit. Indexing was local and used no model calls; retries and unnecessary reads were not measured. The source snapshots matched; raw records are in the local workspace under `work/memory-pilot-20261115`.

A separate diagnostic run explicitly requested `get_task_context` before source inspection. Codex called it successfully, and the compact response identified the approved current lesson and the relevant handler within a 250-token estimated budget. The task passed acceptance; provider-reported usage was 91,920 tokens, including 84,864 cached input tokens. Its prompt explicitly requested a tool call, unlike the prior pair, so the counts are not a matched comparison and do not establish a saving or the cost of that call. The trace is in `work/memory-pilot-explicit-tool-20261115`.

Two further matched single-task pairs tested putting a bounded approved-memory brief in the initial task prompt, without connecting an MCP server. Each arm used the same starting source and task, isolated profiles, and passed public and independent acceptance checks. Pair 1 used a manually assembled brief: baseline 75,429 tokens versus 65,026 with the brief (13.8% fewer). Pair 2 used the new `context --prompt` CLI output and reversed execution order: baseline 49,721 versus 65,560 with the brief (31.9% more). The brief is the intended intervention, so prompts necessarily differed. Each pair is one observation on a tiny fixture; the mixed results do not demonstrate reliable savings. Cached input was 60,672 versus 50,304 in pair 1 and 44,544 versus 50,560 in pair 2. Indexing was local without model calls; provider usage includes the brief, while local preparation time was not included in agent elapsed time. Raw traces are in `work/memory-pilot-prefetch-20261115` and `work/memory-pilot-cli-prefetch-20261115`.

A subsequent NB03-only experiment added startup guidance to batch small-task reads. The matched baseline used 77,617 provider-reported tokens and LazyToken used 92,887; both passed acceptance. This single pair does not prove causation, and the extra guidance was removed because it showed no benefit. The graph was not used to establish a saving. Traces are in the local Codex workspace under `work/token-pilot-batched-nb03`.

One additional matched run per condition repeated the same three cold-start notebook tasks with isolated stores and Codex gpt-6-luna at medium reasoning. All six runs passed their public and independent acceptance checks. Totals below are provider-reported input plus output tokens; indexing used no model calls.

| Task | Baseline | LazyToken enabled | Difference |
| --- | ---: | ---: | ---: |
| NB06 | 75,302 | 63,445 | -11,857 |
| NB03 | 64,379 | 90,101 | +25,722 |
| NB04 | 79,462 | 63,866 | -15,596 |
| Total | 219,143 | 217,412 | -1,731 (0.79%) |

None of the LazyToken runs called an MCP tool. These small, single-observation comparisons do not establish graph savings or a causal effect; model choices and order may affect results. Retries and unnecessary reads were not measured. The runner initially recorded retries as zero without measuring them; the saved records were corrected to unknown. Raw isolated traces remain in the local Codex workspace under `work/token-pilot-final-20261115`. The separate multi-file and reviewed-memory fixture still needs a matched agent trial.

This is a small measured pilot, not proof of a general token-saving benefit. It used Codex CLI 0.169.0-alpha.11.1 with explicitly requested GPT-6-Luna at medium reasoning. Every condition received fresh copies of the same notebook fixture and passed the existing tests and independent acceptance checks.

## Same-case Ponytail comparison

NB06 rejects empty/whitespace-only notebook titles before changing storage, preserves valid titles verbatim and adds regression tests.

| Condition                    | Input tokens | Output tokens |  Total | Change vs baseline | Agent + indexing seconds |
| ---------------------------- | -----------: | ------------: | -----: | -----------------: | -----------------------: |
| Baseline                     |       75,060 |           687 | 75,747 |                  — |                    26.73 |
| Ponytail 5.3.3 primary skill |       70,880 |           807 | 71,687 |             -5.36% |                    26.45 |
| LazyToken enabled            |       64,010 |         1,290 | 65,300 |            -13.79% |                    35.28 |

The exact Ponytail primary skill was installed in an isolated user-skills folder and explicitly invoked. Its successful file read is in the trace; LazyToken was disabled in that condition. Its SHA-256 was `f18008471528f0adde90a560d053f85935eed5cee26c447b7177ad24472bcf32`.

**LazyToken made zero graph/MCP calls in this case.** It was enabled with compact tools and startup guidance, but the agent used ordinary code tools. The numbers therefore do not demonstrate graph-retrieval savings or establish a causal ranking. There was only one observation per condition, and Ponytail ran after the other two.

## Other completed cases

| Case                      | Baseline total | LazyToken-enabled total |  Change |
| ------------------------- | -------------: | ----------------------: | ------: |
| NB06: title validation    |         75,747 |                  65,300 | -13.79% |
| NB03: tag filtering       |         62,839 |                 107,416 | +70.94% |
| NB04: unarchive operation |         76,167 |                  63,505 | -16.62% |
| Combined                  |        214,753 |                 236,221 | +10.00% |

All six runs passed acceptance checks. LazyToken was not queried through MCP in any of them. Its three-case aggregate used **10% more total tokens**, so the two individual reductions must not become a blanket savings claim. Ponytail has no three-case aggregate because it was tested only on NB06.

In NB03, the LazyToken-enabled agent wrote a test expecting a note containing `No project here` not to match `project`. The implementation correctly matched it; the agent fixed the fixture and reran the test. That run used 44,577 more tokens than its baseline. The retry is observed, but one run cannot establish why the agent made the mistake or how much of the difference it caused. The graph was never called, so this is not evidence of a graph defect or graph savings.

Future comparisons should include unfamiliar multi-file tasks and repeated tasks with approved prior lessons, with matched settings and snapshots. Record provider-reported input and output tokens, success, retries, graph calls and repeated reads; leave unavailable measurements unknown. Run real agent tasks only with separate authorization.

## Evidence and limitations

- Starting snapshot: `sha256:df791bc954e9106c81a68f2f19703d49cf2e8da02dc54b2d4079801e926ad326`; relative names and starting bytes, including common safety instructions, were identical. LazyToken v0.4.4 working-tree implementation hash: `74f4ae25c40b8b744dd5b6bb6cf1ccc96fd43a7fd37f3a8e458b73fcd785b0bd`.
- Raw counts came from Codex `turn.completed.usage`. Total means reported input plus output. Cached input is a subset, not an additional charge to the token count. Local indexing made no model calls. Separate tool-overhead allocation, dollar cost and unnecessary-read labels remain unknown.
- Original starting tests were also rerun independently against all seven successful outputs. Profiles, skills and fixture databases were isolated; no prior project memories or task solutions were seeded. This is a cold-start micro-fixture, not a long-session memory study.
- Two preliminary attempts failed on the desktop process environment and MCP approval setup. Their 204,674 reported tokens are retained separately and excluded from successful-task comparisons. Including those failures, recorded benchmark-agent usage was 727,335 tokens. This excludes the evaluator chat's unmeasured usage.
- The corrected environment removed desktop-only child environment variables, used disposable private profiles outside the OS temporary directory and explicitly approved only the fixture-scoped MCP server. Workspace-write sandboxing stayed enabled; production data and real client settings were not test fixtures.
- Baseline/LazyToken order alternated across cases. There were no repetitions, randomized trials, confidence intervals, large-repository tasks or warmed project memories. Client choices, caching and run-to-run variation remain confounders.

Canonical records, raw traces, completed code, skill provenance and test evidence are retained locally under the ignored `benchmark/results/2026-11-15-pilot/` directory and in the delivered artifact bundle. They are not automatically published. See Codex's [non-interactive JSONL documentation](https://learn.chatgpt.com/docs/non-interactive-mode) for usage capture. Future agent runs require separate authorization.
