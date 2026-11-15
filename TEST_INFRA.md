# E2E Test Infra: LazyToken

## Test Philosophy
- **Requirement-Driven & Opaque-Box**: All tests validate user requirements and acceptance criteria from `ORIGINAL_REQUEST.md` (R1–R4) and features specified in `PROJECT.md` (Features 1–16).
- **Interface Decoupling**: Tests interact with LazyToken strictly as an end user / client system:
  1. Command-Line Interface (`kn.py` subcommands via CLI execution).
  2. MCP Server Protocol (Stdio JSON-RPC 2.0 requests: `initialize`, `tools/list`, `tools/call`, `resources/list`, `resources/read`).
  3. Public Python APIs (`kn.sync`, `kn.search`, `kn.context`, `broker.task_context`, `broker.session_checkpoint`, etc.).
  4. Local Dashboard HTTP endpoints (`/api/session/<id>`, `/api/projects`).
  No test may import or assert on internal private functions (`_private`).
- **Complete Test Isolation**:
  - Every test run or test suite initializes a dedicated temporary directory (`tempfile.TemporaryDirectory()`).
  - `KN_HOME` is pointed to the temporary directory so `network.sqlite3` is created in complete isolation.
  - `LAZYTOKEN_DISABLE_AUTOWATCH=1` is set to eliminate background watcher noise and file locks.
  - Dashboard server binds to port 0 (`127.0.0.1:0`) to ensure collision-free loopback testing.
  - Zero external network dependencies: 100% offline and loopback only.
- **Methodology**: Systematic 4-tier design:
  - Category-Partition & Equivalence Partitioning
  - Boundary Value Analysis (BVA) & Stress Testing
  - Pairwise Combinatorial Testing
  - Real-World Multi-Turn Workload & Simulation Testing

---

## Feature Inventory & Test Coverage Matrix

| # | Feature | Requirement Source | Tier 1 (Coverage) | Tier 2 (Boundaries) | Tier 3 (Cross-Feature) |
|---|---------|-------------------|:-----------------:|:-------------------:|:----------------------:|
| F1 | SQLite Concurrency & Reliability (busy_timeout, WAL, indexes) | R1 | 5 | 5 | ✓ |
| F2 | Robust Import/Dependency Matching (no substring false positives, relative paths) | R1 | 5 | 5 | ✓ |
| F3 | Active Session Item Freshness & Deduplication (`updated_at` refresh on suppression) | R1 | 5 | 5 | ✓ |
| F4 | Context Amnesia Elimination & Recovery Recap (breadcrumbs on full suppression) | R1 | 5 | 5 | ✓ |
| F5 | Bulk Candidate Context Queries (batch set queries, no N+1 query loops) | R1, R2 | 5 | 5 | ✓ |
| F6 | BPE Tokenizer Support (tiktoken / HF tokenizers with calibrated fallback) | R2 | 5 | 5 | ✓ |
| F7 | Single-Pass Deterministic Budgeting (O(N) incremental assembly, no 32x loops) | R2 | 5 | 5 | ✓ |
| F8 | High-Density Lean Context & Compact DSL (stripped "why", lean JSON / compact DSL) | R2 | 5 | 5 | ✓ |
| F9 | Unified Context Retrieval Pipeline (shared deduplication and budgeting) | R1, R2 | 5 | 5 | ✓ |
| F10 | Prefix-Cache Optimized Prompts (static declarations before dynamic task) | R2 | 5 | 5 | ✓ |
| F11 | CLI Discoverability & Argparse Unification (dashboard/benchmark in help, zero mojibake) | R3 | 5 | 5 | ✓ |
| F12 | Human-Centric Formatted CLI Output (`--format text\|json\|table`, status indicators) | R3 | 5 | 5 | ✓ |
| F13 | Complete MCP Protocol & Resources (`checkpoint` tool, 18 schemas, MCP resources) | R3 | 5 | 5 | ✓ |
| F14 | Active Session Dashboard UI & Endpoint (`/api/session/<id>` graph inspect) | R3 | 5 | 5 | ✓ |
| F15 | Live Benchmark Suite & Metrics Runner (token savings, compression, recall, latency) | R4 | 5 | 5 | ✓ |
| F16 | Multi-Turn Simulation & Recall Validation (zero unhandled exceptions, 100% recall) | R1, R4 | 5 | 5 | ✓ |
| **Total** | | | **80** | **80** | **16 Pairs** |

---

## Test Architecture

### Directory Layout
```
tests/e2e/
├── __init__.py                     # Package initialization for unittest discovery
├── common.py                       # Base E2ETestCase, CLI runner, McpClient, mock repo generator
├── runner.py                       # Standalone CLI test runner (--tier 1..4, --all, --verbose, --json-report)
├── test_tier1_features.py          # Tier 1: Feature Coverage (80 tests: 5 per Feature 1–16)
├── test_tier2_boundaries.py        # Tier 2: Boundary & Corner Cases (80 tests: 5 per Feature 1–16)
├── test_tier3_combinations.py      # Tier 3: Pairwise & Cross-Feature Workflows (16 combination tests)
└── test_tier4_workloads.py         # Tier 4: Real-World Workloads & Multi-Turn Simulations (8 scenarios)
```

### Test Harness Components (`tests/e2e/common.py`)
1. **`E2ETestCase` (Base Class)**:
   - Inherits from `unittest.TestCase`.
   - Automatically provisions an isolated temporary directory for each test case.
   - Sets environment variables:
     - `KN_HOME`: Points to temporary directory to isolate SQLite database (`network.sqlite3`).
     - `LAZYTOKEN_DISABLE_AUTOWATCH`: `"1"` to prevent unwanted background watcher threads.
   - Provides helper methods:
     - `create_repo(files: dict[str, str]) -> Path`: Creates synthetic source files (Python, JS/TS, Markdown, etc.).
     - `run_cli(args: list[str], check: bool = False, timeout: int = 15) -> CompletedProcess`: Executes `python kn.py ...` with isolated environment.
     - `run_cli_json(args: list[str], check: bool = True) -> dict`: Executes CLI command and parses standard output as JSON.
     - `open_mcp_client() -> McpClient`: Returns an active JSON-RPC stdio client.
2. **`McpClient`**:
   - Manages a subprocess running `python kn.py mcp`.
   - Sends newline-delimited JSON-RPC 2.0 requests over stdin and reads responses from stdout.
   - Methods:
     - `initialize(protocol_version="2024-11-05") -> dict`
     - `ping() -> dict`
     - `list_tools() -> list[dict]`
     - `call_tool(name: str, arguments: dict) -> dict`
     - `list_resources() -> list[dict]`
     - `read_resource(uri: str) -> dict`
     - `close()`
3. **`TestRunner` (`tests/e2e/runner.py`)**:
   - Standalone executable runner: `python tests/e2e/runner.py [--tier 1|2|3|4] [--all] [--verbose] [--json-report PATH]`.
   - Integrates cleanly with standard library discovery: `python -m unittest discover tests`.
   - Exit code: `0` on all tests passing, `1` on any failure or error.

---

## Real-World Application Scenarios (Tier 4)

| # | Scenario | Features Exercised | Complexity | Target Acceptance Criteria |
|---|----------|--------------------|------------|----------------------------|
| S1 | 10-Turn Incremental Refactoring Session | F1, F3, F4, F7, F8, F16 | High | Multi-turn stateful refactoring session; zero exceptions; zero amnesia; foundational items recalled; >60% token compression. |
| S2 | Multi-Interface Sync & Query Cycle (CLI ↔ MCP ↔ Dashboard) | F1, F11, F13, F14 | High | CLI indexes repository; MCP retrieves multi-turn task context; Dashboard HTTP endpoint `/api/session/<id>` accurately serves session graph. |
| S3 | BPE Tokenizer & Single-Pass Optimization Pipeline | F6, F7, F8, F9, F10 | Medium | High-budget context retrieval with lean DSL representation and prefix-cache aligned prompts; achieves >75% token reduction vs unoptimized raw JSON. |
| S4 | Live Benchmark & Evaluation Harness Execution | F15, F16 | Medium | Running `python kn.py benchmark run` and evaluation scripts produces structured metrics for token savings, compression ratio, and retrieval latency. |
| S5 | High-Concurrency Multi-Client Read/Write Stress | F1, F5, F13 | High | 8 concurrent worker threads/subprocesses issuing simultaneous writes, searches, and context queries; zero database lock errors. |
| S6 | Cross-Language Monorepo AST & Import Resolution | F2, F5, F9 | Medium | Multi-language project (Python, TypeScript, Markdown); verify precise import resolution without false-positive substring matches (e.g. `re` -> `features.py`). |
| S7 | Propose, Review, and Dynamic Memory Recall Cycle | F1, F3, F4, F9, F12 | Medium | Propose lesson; review and approve; query context to verify lesson is recalled; modify source and sync to verify freshness state transition. |
| S8 | Fault Recovery & Corpus Checkpoint Restoration | F3, F4, F13, F16 | High | Crash simulation mid-session; checkpoint restoration via MCP `checkpoint` and CLI `checkpoint`; verify complete graph reconstruction. |

---

## Coverage Thresholds & Pass Criteria

- **Tier 1 (Feature Coverage)**: ≥5 tests per feature across all 16 features (Total ≥80 tests).
- **Tier 2 (Boundary & Corner Cases)**: ≥5 boundary tests per feature across all 16 features (Total ≥80 tests).
- **Tier 3 (Cross-Feature Combinations)**: ≥16 pairwise combination integration tests.
- **Tier 4 (Real-World Scenarios)**: ≥8 complex end-to-end multi-turn application scenarios.
- **Total Suite**: ≥184 comprehensive opaque-box E2E tests.
- **Pass Semantics**:
  - Full test suite executes cleanly via `python tests/e2e/runner.py --all` with exit code `0`.
  - Zero unhandled exceptions or crashes.
  - Zero regressions on existing 121 unit tests (`python -m unittest discover tests`).
