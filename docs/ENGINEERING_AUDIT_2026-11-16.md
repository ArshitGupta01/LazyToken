# Code intelligence audit — 2026-11-16

Baseline: TokSmart/LazyToken checkout `e8e115e`, SQLite-backed local Python runtime. Reference source inspected at GitNexus `2e8f01304eed5384f1ac2ec8a2efee1e1fddf55f` and Codebase Memory MCP `cdfdf26483fa56f4f7d9d85e7c4c3924133b458b`. This is an initial targeted assessment, not an exhaustive license or whole-codebase audit.

## Findings and design choices

| Subsystem | Current implementation | Reference observations and direction |
| --- | --- | --- |
| Trust boundary | The dashboard exposed all JSON through wildcard CORS and accepted arbitrary `*.vercel.app` review origins. | First restrict hosted access to health detection and serve private data and review from the local origin. Browser loopback permission is not authorization. |
| Indexing | Python AST and custom JS/TS extraction populate SQLite files, symbols, imports and calls; incremental sync uses project generations. | Codebase Memory MCP uses staged parallel extraction, registry construction and call resolution. Keep one SQLite store; improve discovery failures and confidence first. |
| Parsing and resolution | Python static inference and JS syntax heuristics can miss or mislabel relationships. | GitNexus uses Tree-sitter; evaluate a pinned JS/TS grammar on independently labelled fixtures. Syntax parsing alone cannot resolve dynamic dispatch. Check each grammar license and platform wheel before adding it. |
| Search | SQLite FTS5 supplies metadata hit signals; hand-weighted lexical scoring determines ordering, without source-body indexing. | GitNexus combines FTS and optional embeddings with reciprocal rank fusion. Codebase Memory MCP uses SQLite FTS5 BM25. Compare built-in BM25 against the current ranker before choosing it; retain exact identifier matches and deterministic fallback. Do not claim calibrated confidence for lexical matches. |
| Graph | Import and call relationships exist, but context graph edges connect files already selected or seen; they do not necessarily introduce a relevant dependency. | Measure a bounded, scoped dependency-expansion experiment against the same labels and token budget. Do not add another database without evidence. |
| Memory | Project/session-scoped checkpoints, fingerprints and reviewable lessons are separate from code graph data. | Preserve the distinction. Test process termination, stale evidence and migration; never present caller-reported test outcomes as independently verified. |
| Tokens | Payload counts use a configured offline tokenizer or a character estimate; schema and framing are estimates. | Preserve explicit fidelity labels. Only provider-reported paired task usage and correctness can support savings claims. |
| Synchronization | Watcher polls metadata and periodically verifies content; each poll inventories eligible files. | Measure real repositories, CPU, latency and missed changes before adopting a platform watcher. Retain periodic reconciliation and safe fallback. |
| MCP | Local stdio JSON-RPC handler executes requests serially. | Measure contention and interoperability before replacing it. Preserve scope, notifications and error behavior. |

## Licensing

[GitNexus's PolyForm Noncommercial license](https://github.com/abhigyanpatwari/GitNexus/blob/2e8f01304eed5384f1ac2ec8a2efee1e1fddf55f/LICENSE) restricts permitted purposes. Do not copy its source into a generally commercially usable distribution. [Codebase Memory MCP is MIT licensed](https://github.com/DeusData/codebase-memory-mcp/blob/cdfdf26483fa56f4f7d9d85e7c4c3924133b458b/LICENSE), but its vendored parsers and other dependencies have their own licenses. No reference source has been incorporated; inspect each prospective dependency and retain required notices before distribution.

## Baseline and measurement limits

The baseline core suite ran 273 tests, with 268 passing and five skipped. The existing 28 synthetic, agent-authored retrieval cases reported recall@5 0.917; their labels have not been independently reviewed and two missing results have questionable expected labels. This is not a real-repository accuracy claim. Existing graph ablation needs correction before its memory and output-size comparisons can support conclusions.

After the first fixes, those synthetic aggregate metrics were unchanged. A separate one-run smoke comparison on Werkzeug commit `0f43c6ebd426039e4b99ec22535c2c8a2ec2f69f` indexed 207 eligible files and used six manually source-checked definition-file labels. Both baseline `e8e115e` and a working-tree snapshot returned the expected file in the top five for five of six queries; the `Client test application` query missed `src/werkzeug/test.py`. The labels are not exhaustive or independently reviewed, the working snapshot was captured during integration, and baseline ran first; timings are confounded by cache warming. This does not demonstrate a speed, accuracy, or provider-token improvement. Raw results and harness are retained under the local temporary directory `lt-real-eval-7cb735ee592d4b6aaf21a1e41ad6d420`.

For meaningful comparisons, pin multiple real repositories and task sets, independently review relevant paths, use the same tasks and budgets for grep, baseline and candidate, and report per-repository recall, precision, MRR, abstention, latency, index time and peak memory. Separately run repeated order-reversed agent tasks with hidden correctness checks and provider-reported input/output usage. Keep failures and unavailable measurements visible.

## Prioritized stages

1. Close the dashboard origin boundary and preserve indexes on transient discovery failures. Test hostile origins, local reviews, unreadable files and actual deletions.
2. Correct proven parser and task truncation bugs, retaining conservative confidence and extractor-version refresh.
3. Repair benchmark accounting, build independently reviewed real-repository cases, then evaluate FTS5 BM25 and bounded graph expansion against the existing implementation.
4. Evaluate Tree-sitter for JS/TS using syntax accuracy, platform wheels, memory, indexing time and each dependency license. Keep Python `ast` and the existing fallback until a measured replacement is justified.
5. Measure watcher scaling, process-kill recovery, concurrency and MCP compatibility; change infrastructure only where the measurements justify it.
6. Evaluate optional semantic retrieval, model-specific tokenization and richer session memory only after relevance and end-to-end correctness baselines exist. Never infer task savings from a smaller payload.

Risks across stages include changed ranking, stale indexes after extractor changes, schema migration and rollback, package footprint, cross-platform parser availability, and accidental exposure of source text. Each stage needs focused regression tests and a paired baseline; expected gains remain hypotheses until measured.
