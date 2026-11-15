# E2E Test Infra: LazyToken Phase 2 & Phase 3

## Test Philosophy
- **Opaque-Box & Requirement-Driven**: Tests validate external contracts, CLI commands, HTTP/MCP endpoints, and SQLite state without coupling to internal private helper functions.
- **Methodology**: Systematic 4-tier testing hierarchy combining:
  1. *Category-Partition & Equivalence Partitioning*: Partitioning inputs into valid/invalid classes across all features.
  2. *Boundary Value Analysis (BVA)*: Stressing limits (0 tokens, negative numbers, 10k character queries, max depth, empty databases, max file counts).
  3. *Pairwise Combinatorial Testing*: Exercising interactions between independently developed features (e.g., Session State + WAL concurrency, Memory Governance + Dashboard API).
  4. *Real-World Workload Simulation*: High-turn agent workflows simulating realistic developer sessions with context compaction, state rehydration, and memory governance.
- **Zero-Regression Mandate**: All existing 169 unit tests and 184 E2E tests must maintain 100% pass rate. All new features are additive.

---

## Feature Inventory
Comprehensive mapping of all 22 LazyToken features across the 4-tier test architecture:

| # | Feature | Source (Requirement) | Tier 1 (Coverage) | Tier 2 (Boundaries) | Tier 3 (Combinations) |
|---|---------|----------------------|:-----------------:|:-------------------:|:---------------------:|
| 1 | SQLite Concurrency & WAL mode | Baseline Architecture | 5 tests | 5 tests | C1, C19 |
| 2 | Robust Import Matching | Baseline Code Intelligence | 5 tests | 5 tests | C2 |
| 3 | Session Freshness & Deduplication | Baseline Session State | 5 tests | 5 tests | C1, C3 |
| 4 | Context Amnesia Elimination | Baseline Memory Recall | 5 tests | 5 tests | C4, C22 |
| 5 | Bulk Candidate Context Queries | Baseline Performance | 5 tests | 5 tests | C5 |
| 6 | BPE Tokenizer Support & Fallback | Baseline Token Accounting | 5 tests | 5 tests | C6 |
| 7 | Single-Pass Deterministic Budgeting | Baseline Broker Policy | 5 tests | 5 tests | C7 |
| 8 | High-Density Lean Context Formatting | Baseline Formatting | 5 tests | 5 tests | C8 |
| 9 | Unified Context Retrieval Pipeline | Baseline Search Pipeline | 5 tests | 5 tests | C9 |
| 10 | Prefix Cache Optimized Prompts | Baseline Context Assembly | 5 tests | 5 tests | C10 |
| 11 | CLI Discoverability (argparse) | Baseline CLI Interface | 5 tests | 5 tests | C11 |
| 12 | Human-Centric Formatted CLI Output | Baseline CLI UX | 5 tests | 5 tests | C12 |
| 13 | Complete MCP Protocol Resources & Tools | Baseline Integration | 5 tests | 5 tests | C13, C23 |
| 14 | Active Session Dashboard | Baseline UI Review | 5 tests | 5 tests | C14, C21 |
| 15 | Live Benchmark Suite & Metrics Runner | Baseline Evaluation | 5 tests | 5 tests | C15 |
| 16 | Multi-Turn Simulation & Recall Validation | Baseline Multi-Turn | 5 tests | 5 tests | C16 |
| 17 | Five-Mode Retrieval Ablations (Plain Grep, Lexical, Lexical+Graph, Memory, Full) | R1 (LT-P1-201) | 5 tests | 5 tests | C17 |
| 18 | Cost-Aware Retrieval Policy & Utility Ranking (`why_this_context`) | R2 (LT-P1-202) | 5 tests | 5 tests | C17, C18 |
| 19 | Model & Token Budget Fidelity (Schema Tax, Framing, Approximation) | R3 (LT-P1-203) | 5 tests | 5 tests | C18 |
| 20 | Persistent Task-Session State & Recovery (Idempotent, Invalidation) | R4 (LT-P1-301) | 5 tests | 5 tests | C19, C20, C24 |
| 21 | Memory Quality Lifecycle Governance & Evidence Linking | R5 (LT-P1-302) | 5 tests | 5 tests | C21, C22, C23, C24 |
| 22 | Architectural Hardening & Code Intelligence (`super()`, Language Transparency) | R6, Audit Items 1,5,6,7 | 5 tests | 5 tests | S9 |

---

## Test Architecture

### 1. Test Directory Layout
```
d:\LazyToken\
├── tests\                                # Unit and integration test suites
│   ├── test_*.py                         # Existing 21 test files (169 baseline unit tests)
│   ├── test_token_budget_fidelity.py     # New M1/F19 unit tests
│   ├── test_cost_aware_policy.py         # New M2/F18 unit tests
│   ├── test_retrieval_ablation_5modes.py # New M3/F17 unit tests
│   ├── test_task_session_state.py        # New M4/F20 unit tests
│   └── test_memory_lifecycle.py          # New M5/F21 unit tests
├── benchmark\                            # Benchmark evaluation & synthetic ablation fixtures
│   ├── graph_ablation.py                 # 5-mode empirical ablation suite (incorporates Plain Grep)
│   ├── retrieval_assessment.py           # Multi-scenario assessment runner
│   ├── retrieval_cases.json              # Expanded benchmark cases with ground-truth labels
│   └── harness.py                        # Benchmark run validator and comparison engine
└── e2e\                                  # End-to-End hierarchical testing framework
    ├── runner.py                         # Standalone CLI test runner (--tier {1,2,3,4}, --all, --json-report)
    ├── common.py                         # E2ETestCase base, McpClient, isolated temp repos & DB fixtures
    ├── test_tier1_features.py            # Tier 1: Feature coverage (F1-F16 existing + F17-F21 new = 105 tests)
    ├── test_tier2_boundaries.py          # Tier 2: Boundary & corner cases (F1-F16 + F17-F21 = 105 tests)
    ├── test_tier3_combinations.py        # Tier 3: Pairwise combinations (C1-C16 existing + C17-C24 new = 24 tests)
    └── test_tier4_workloads.py           # Tier 4: Real-world complex workloads (S1-S8 existing + S9 new = 9 tests)
```

### 2. Test Execution & Pass/Fail Semantics
- **Unit Test Discovery**: `python -m unittest discover -s tests -p "test_*.py"`
  - Executes all unit tests in isolated subprocess/fixtures.
  - Exit code 0 indicates success.
- **E2E CLI Runner**: `python e2e/runner.py --all`
  - Runs all 4 tiers sequentially.
  - Supports `--tier 1`, `--tier 2`, `--tier 3`, `--tier 4` for target-scoped runs.
  - Supports `--json-report <path>` for automated CI/gate consumption.
  - Exit code 0 if all tests pass; non-zero on any failure or error.
- **Benchmark Execution**: `python benchmark/graph_ablation.py`
  - Evaluates all 5 ablation modes across synthetic multi-component scenarios.
  - Outputs comparative metrics (Precision@k, Recall@k, MRR@k, NDCG@k, Abstention, Tokens, Savings%).

---

## Detailed Specification: Phase 2 & 3 Test Suites

### Tier 1: Feature Coverage (F17–F21, 5 tests each = 25 tests)

#### F17: 5-Mode Empirical Retrieval Evaluation
- `test_f17_mode1_plain_grep_baseline`: Verifies raw file/grep baseline without SQLite FTS or graph.
- `test_f17_mode2_lexical_no_graph`: Verifies FTS/BM25 retrieval isolated from graph expansion.
- `test_f17_mode3_lexical_with_graph`: Verifies lexical search combined with AST relational call graph expansion.
- `test_f17_mode4_verified_memory_no_graph`: Verifies retrieval using saved verified lessons alone without AST graph.
- `test_f17_mode5_full_lazytoken_pipeline`: Verifies full pipeline combining lexical, memory, and AST call graph expansion.

#### F18: Cost-Aware Retrieval Policy & Utility Ranking
- `test_f18_conservative_task_classifier_skip`: Verifies classifier skips retrieval for self-contained/formatting/greeting tasks.
- `test_f18_conservative_task_classifier_abstain`: Verifies classifier abstains when candidate relevance is below threshold.
- `test_f18_expected_utility_per_token_ranking`: Verifies candidates are ordered by `(relevance * freshness * verification) / tokens`.
- `test_f18_progressive_context_expansion`: Verifies context dynamically expands when initial context is insufficient or deep mode is set.
- `test_f18_why_this_context_explanations`: Verifies concise explanation strings accompany retrieved items and `why` remains backward-compatible.

#### F19: Token Budget Fidelity & Framing Overhead
- `test_f19_mcp_schema_overhead_distinction`: Verifies tool catalog overhead is accounted for separately from payload tokens (~713 compact vs ~2371 full).
- `test_f19_chat_framing_overhead_accounting`: Verifies chat framing (~25 tokens/turn) is distinguished from payload.
- `test_f19_approximation_labeling`: Verifies character-based estimates (chars/4) are explicitly flagged with `is_approximate: True` and never described as exact.
- `test_f19_token_accounting_structure`: Verifies structured `token_accounting` dict contains all required fields (`payload_tokens`, `total_context_footprint_tokens`, `fidelity`).
- `test_f19_budget_scope_and_uncertainty`: Verifies budget counters preserve explicit `budget_type` descriptions.

#### F20: Persistent Task-Session State & Recovery
- `test_f20_task_session_schema_migration`: Verifies Migration 6 creates `task_sessions`, `session_decisions`, `session_blockers`, `session_test_outcomes`, `session_breadcrumbs`.
- `test_f20_session_checkpoint_persistence`: Verifies goals, working set, decisions, blockers, test outcomes, symbols, and breadcrumbs persist across restarts.
- `test_f20_epistemic_layering_separation`: Verifies clear boundary between observed (AST/index), asserted (agent claims), and verified (passing test execution) states.
- `test_f20_source_version_invalidation`: Verifies session checkpoint detects file modifications and emits `source_invalidation` signal.
- `test_f20_idempotent_session_recovery`: Verifies repeated recovery calls produce identical, stable state snapshots with zero side effects.

#### F21: Memory Quality Lifecycle Governance & Evidence Linking
- `test_f21_memory_lifecycle_state_machine`: Verifies state progression: `pending` -> `reviewed` -> `verified` -> `stale` / `superseded`.
- `test_f21_legitimate_corrections_with_replaces_id`: Verifies `replaces_id` bypasses duplicate checks and supersedes previous memory on approval.
- `test_f21_test_evidence_linking`: Verifies lessons are linked to evidence files, test commands, exit codes, and digests in `memory_test_evidence`.
- `test_f21_governance_export_retention_delete`: Verifies `export_memories` (JSON/MD), `retention_memories` (prune stale), and `delete_memory` without touching user source files.
- `test_f21_human_review_policy_guard`: Verifies agent suggestions cannot be promoted to verified memory without explicit human review via dashboard API.

---

### Tier 2: Boundary & Corner Cases (F17–F21, 5 tests each = 25 tests)

- **F17 Boundaries**:
  - `test_f17_b1_empty_ablation_repository`: Graceful empty results when no source files exist.
  - `test_f17_b2_zero_match_ablation_query`: Abstention and 0-score handling when query matches nothing.
  - `test_f17_b3_single_file_repo_ablation`: Evaluates ablation modes on repository with only a single file.
  - `test_f17_b4_extreme_k_values`: Evaluates metrics at k=0 and k=1000 without indexing errors.
  - `test_f17_b5_ablation_score_tie_breaking`: Deterministic ordering when multiple candidates have identical relevance.

- **F18 Boundaries**:
  - `test_f18_b1_empty_task_string`: Handling empty or whitespace task descriptions gracefully.
  - `test_f18_b2_huge_task_payload_10k_chars`: 10,000-character task prompt parsed without buffer overflows or excessive latency.
  - `test_f18_b3_conflicting_intent_keywords`: Task containing both "greeting" and "deep architecture refactor" properly classified.
  - `test_f18_b4_all_stopwords_task`: Task with only common English stop-words handled gracefully.
  - `test_f18_b5_zero_and_negative_utility_clamp`: Zero tokens or negative utility scores safely clamped to non-zero floor.

- **F19 Boundaries**:
  - `test_f19_b1_zero_payload_tokens`: Correct schema overhead accounting when payload is 0 tokens.
  - `test_f19_b2_negative_token_clamp`: Negative token counts safely clamped to 0.
  - `test_f19_b3_extreme_turn_count_10k_turns`: Chat framing computed accurately for 10,000 turns without overflow.
  - `test_f19_b4_unknown_model_fallback`: Fallback to character approximation when model is unspecified or unknown.
  - `test_f19_b5_huge_token_footprint`: Context footprint exceeding 1,000,000 tokens tracked without precision loss.

- **F20 Boundaries**:
  - `test_f20_b1_empty_session_id`: Clean validation error on empty session identifier.
  - `test_f20_b2_nonexistent_project_recovery`: Graceful 404/empty response when recovering state for unindexed project.
  - `test_f20_b3_rapid_successive_compactions`: 50 rapid session state updates in a loop with transaction integrity.
  - `test_f20_b4_corrupted_json_breadcrumbs`: Graceful degradation when session breadcrumb JSON payload is malformed.
  - `test_f20_b5_massive_source_invalidation_1000_files`: Source invalidation correctly aggregates when 1000 files are modified.

- **F21 Boundaries**:
  - `test_f21_b1_duplicate_proposal_rejection`: Exact duplicate proposal text rejected with clear conflict error.
  - `test_f21_b2_circular_replaces_id_chain`: Circular replacement cycles (`A -> B -> A`) prevented.
  - `test_f21_b3_self_replacing_memory`: Proposal attempting to replace its own ID rejected.
  - `test_f21_b4_illegal_state_transitions`: Direct jumps from `pending` -> `superseded` without review blocked.
  - `test_f21_b5_huge_test_evidence_payload`: 50KB test stdout log stored and truncated safely without crashing SQLite.

---

### Tier 3: Pairwise Combinations (C17–C24, 8 tests)

- **C17: F17 (5-Mode Ablation) + F18 (Cost-Aware Policy)**:
  - `test_c17_ablation_with_conservative_task_classifier`: Verifies ablation runner skips retrieval when classifier classifies task as self-contained.
- **C18: F18 (Cost-Aware Policy) + F19 (Token Budget Fidelity)**:
  - `test_c18_utility_ranking_with_schema_framing_budget`: Verifies utility-ranked context fits precisely within budget after subtracting MCP schema tax and chat framing.
- **C19: F20 (Session State Recovery) + F1 (SQLite WAL Concurrency)**:
  - `test_c19_concurrent_session_checkpoints_wal`: Verifies multiple concurrent worker threads reading and writing session checkpoints simultaneously under WAL mode.
- **C20: F20 (Session State Recovery) + F11 (Source Version Invalidation)**:
  - `test_c20_session_recovery_after_external_file_modification`: Modifying repository source files on disk triggers `source_invalidation: True` upon session checkpoint recovery.
- **C21: F21 (Memory Quality Lifecycle) + F14 (Dashboard Review API)**:
  - `test_c21_memory_lifecycle_reviewed_via_dashboard_api`: Proposes a lesson, verifies `pending` state, approves via HTTP `/api/review` with CSRF token, and verifies transition to `verified`.
- **C22: F21 (Memory Quality Lifecycle) + F4 (Context Recall)**:
  - `test_c22_verified_lesson_recalled_with_why_this_context`: Verified lesson is dynamically recalled in `broker.task_context` and annotated with `why_this_context`.
- **C23: F21 (Memory Corrections `replaces_id`) + F13 (MCP Protocol Tools)**:
  - `test_c23_corrective_memory_supersession_via_mcp`: Submits corrective memory with `replaces_id` via MCP tool; verifies previous memory is superseded upon approval.
- **C24: F20 (Session State Recovery) + F21 (Memory Lifecycle)**:
  - `test_c24_session_compaction_preserves_verified_memory_evidence`: Session compaction preserves active working set and links memory proposals to verified test outcomes.

---

### Tier 4: Real-World Application Scenarios (S9)

#### S9: Stateful Compaction & Multi-Turn Memory Governance Workload
- **Scenario ID**: `S9`
- **Complexity**: High (15-turn multi-step agent workflow)
- **Features Exercised**: F1, F3, F4, F7, F8, F14, F17, F18, F19, F20, F21, F22
- **Description**:
  1. Initializes a multi-component e-commerce repository (`cart.py`, `order.py`, `payment.py`, `discount.py`).
  2. Simulates a 15-turn development workflow where the agent analyzes requirements, identifies a race condition in order processing, and writes a test.
  3. Periodically compacts context (Turns 5 and 10), verifying that goals, decisions, blockers, and verified test outcomes persist in SQLite `task_sessions`.
  4. Modifies `cart.py` between turns to verify that session recovery accurately detects `source_invalidation`.
  5. Agent discovers a domain lesson ("apply idempotency key before payment deduction"), proposes it with test evidence, and approves it via dashboard API `/api/review`.
  6. Later submits a corrective lesson replacing the prior one with `replaces_id`.
  7. Final context assembly verifies the corrected memory is recalled with `why_this_context`, payload tokens fit strict budget after schema tax subtraction, and session recovery is 100% idempotent.

---

## Coverage Thresholds
- **Tier 1 (Feature Coverage)**: ≥5 tests per feature (Features 1–21: 21 × 5 = 105 tests).
- **Tier 2 (Boundary & Corner)**: ≥5 tests per feature (Features 1–21: 21 × 5 = 105 tests).
- **Tier 3 (Cross-Feature Combinations)**: 24 pairwise integration tests (C1 through C24).
- **Tier 4 (Real-World Application Scenarios)**: 9 realistic application workloads (S1 through S9).
- **Total E2E Suite Target**: **243 E2E Tests** (184 baseline + 59 new tests).

---

## Pass/Fail Gate Criteria
1. `python -m unittest discover -s tests -p "test_*.py"`: 100% PASS (zero regressions on baseline 169 tests + new unit tests).
2. `python e2e/runner.py --all`: 100% PASS (all 243 tests pass with exit code 0).
3. `python benchmark/graph_ablation.py`: Executes all 5 ablation modes across all 4 scenarios with clean Markdown output.
4. Loopback Dashboard tests (`tests/test_dashboard_review.py`): 100% PASS.
