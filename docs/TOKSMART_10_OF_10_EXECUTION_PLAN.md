# TokSmart: two-day 10/10 execution plan

**Baseline audited:** `da8f66bc2b7ece6a267db3d8d387c3ad3568abb5` (2026-11-16)  
**Product:** a local-first code graph, deterministic search and reviewed memory system for AI-assisted coding, with a separate mobile prompt hub.  
**Rule for this sprint:** preserve the local-first privacy model and make only evidence-backed claims about retrieval or token savings. Do not substitute a cosmetic rewrite for a tested product improvement.

## What is already strong

- The core is deliberately dependency-light: Python standard library, SQLite, vanilla browser UI, local loopback dashboard, and static analysis without executing indexed project code.
- The source tree has meaningful coverage: Python unit tests, four E2E tiers, Node tests for workspace/mobile behavior, formatting checks, Linux/Windows CI, and Windows release smoke coverage.
- The current dashboard boundary is substantially hardened: it binds to loopback, validates Host and Origin, limits cross-origin access to health checks, uses an in-memory review token for mutations, reads the graph read-only, sends CSP/nosniff/no-store headers, and constrains static asset paths.
- The mobile experience has canonical, versioned prompts; one copy action per mode; local-only benchmark report import; and explicit limits on what a pasted prompt can prove.
- The benchmark documentation correctly distinguishes provider usage from estimates and warns that existing small pilots do not prove broad token savings.

## Baseline verification

| Check | Result |
| --- | --- |
| `python -m unittest discover -s tests -p 'test_*.py'` | 296 passed, 11 skipped |
| `python e2e/runner.py --all` | 209 passed |
| `node --test tests/mobile.test.cjs tests/workspace.test.cjs` | 16 passed |
| `python -m black --check .` | 78 files unchanged |
| `npx --yes prettier@3.4.2 --check app.js features-ui.js graph3d.js index.html styles.css tests/workspace.test.cjs` | passed |
| `node --check app.js && node --check graph3d.js && node --check features-ui.js` | passed |

The audit ran against a clean checkout. The test suite printed an expected temporary-file-exists exercise during unit tests; the suite still passed.

## Critical audit findings and priorities

1. **P0 — Reconcile product naming and release surface.** Runtime, installer, migration, release and several user-facing diagnostics still expose historical **LazyToken** / **RepoMind** names, while the product is TokSmart. This weakens trust, complicates support, and can make a 10/10 public release look unfinished. Preserve compatibility aliases intentionally; do not accidentally break old database/config migration paths.
2. **P0 — Make claims measurable, not merely polished.** Existing evidence is admirably cautious but is not sufficient to claim general token savings: the documented pilot is tiny, mixed, and contains runs with zero MCP/graph use. The product needs a repeatable public evidence package for retrieval quality and, separately, end-to-end coding-agent results.
3. **P1 — Close test/CI parity gaps.** The npm publish workflow runs only `tests/workspace.test.cjs`, while the main CI additionally runs `tests/mobile.test.cjs`, Prettier, and JS syntax checks. A publish should not have a weaker web/mobile gate than a pull request.
4. **P1 — Accessibility and user-journey evidence are under-specified.** The UI is functional and tested structurally, but no automated keyboard, focus, contrast, reduced-motion, responsive viewport, or screen-reader-name verification is present. Manual review alone is not a release-quality substitute.
5. **P1 — Architecture remains centralized.** `kn.py`, `features.py`, `broker.py`, `source_index.py`, and browser scripts are large, multi-responsibility modules. Do not perform a broad refactor in this 48-hour sprint; first add characterization tests and extract one sharply bounded seam only where it removes an observed defect.
6. **P2 — Performance/scaling claims need fixtures.** Watcher and retrieval behavior are sensibly conservative, but no repeatable performance budget on a representative medium repository is enforced. Benchmarks need cold/warm indexing time, memory, latency, corpus size, and missed-change reporting.
7. **P2 — Static analysis limitations must remain visible.** JavaScript/TypeScript relationship extraction is heuristic; dynamic calls and notebook cells are excluded. Improve diagnostics and capability disclosures before adding parser dependencies or claiming semantic understanding.

## Session plan (eight focused sessions)

Each session must take the next unfinished item, avoid unrelated edits, and finish with targeted tests plus this file updated with the evidence.

| Session | Objective | Required deliverable | Minimum acceptance criteria |
| --- | --- | --- | --- |
| 1 | Build a naming-compatibility inventory. **Completed 2026-11-17.** | `docs/BRAND_COMPATIBILITY.json` plus `tests/test_brand_compatibility.py`. | Every legacy name is categorized as compatibility-only, user-facing bug, or migration contract; no removal yet. |
| 2 | Fix the most visible safe naming defect. **Completed 2026-11-17.** | One narrow user-facing rename or compatibility message improvement, retaining old commands/config/database behavior. | Old and new supported entrypoints work; docs/tests cover both where promised. |
| 3 | Tighten publish CI parity. **Completed 2026-11-17.** | Publish workflow invokes all relevant static/mobile checks or shares a reusable verify workflow. | A release cannot publish if formatting, browser syntax, or mobile tests fail; workflow remains least-privilege. |
| 4 | Add one end-to-end accessibility regression layer. **Completed 2026-11-17.** | Lightweight browser-free semantic checks first (labels, button names, landmarks, live region/focus contract); use Playwright only if it adds real coverage. | Desktop and mobile primary flows are keyboard-operable by design; failure is caught in CI. |
| 5 | Improve first-run/empty-state UX. **Completed 2026-11-17.** | One clear, tested path from “no indexed projects” to successful `serve → add → graph/context`. | No ambiguous localhost/phone language; error state names the next command and does not leak a local path. |
| 6 | Create a reproducible performance fixture. | Script/data format that records index count, elapsed time, retrieval latency, platform and warm/cold status without fabricating results. | No network/model calls; output validates; baseline is reproducible locally and documented. |
| 7 | Add evidence-grade retrieval evaluation. | Independently reviewable real-repository case format and report fields for recall, precision, MRR, abstention, latency and token budget. | Existing synthetic cases remain clearly labeled; no “savings” result without provider usage plus correctness. |
| 8 | Release-readiness pass. | Changelog/release checklist, support matrix, final all-suite run, and a concise known-limitations statement. | All required checks pass; version/docs/package surfaces agree; remaining unproven claims are explicitly marked unknown. |

If a session uncovers a P0 security, data-loss, path-traversal, origin-boundary, or migration issue, stop the sequence and fix that with regression coverage before lower-priority work.

## Definition of 10/10 for this project

TokSmart earns the target only when all of these are true:

- **Trustworthy:** local-data boundary and review mutations have negative tests; package/install/rollback behavior is safe and documented; public claims match evidence.
- **Useful:** a new user can install, index, search, inspect impact, generate bounded context, and understand failures without hand-holding.
- **Correct:** supported languages and static-analysis limits are explicit; results include evidence and scope; upgrades preserve legacy user data/configuration.
- **Polished:** TokSmart naming is coherent, the desktop and phone products explain their different capabilities, and keyboard/mobile behavior is intentionally verified.
- **Maintainable:** CI gates the published artifact, tests are fast and stable, critical modules have characterization coverage, and release instructions are reproducible.
- **Measured:** retrieval quality, index/retrieval performance, and any token/cost benefit are reported with raw inputs, matched conditions, caveats and unknowns rather than extrapolation.

## Standard verification commands

Run the smallest relevant command while developing, then run the full release gate before Session 8:

```sh
python -m black --check .
npx --yes prettier@3.4.2 --check app.js features-ui.js graph3d.js index.html styles.css web/index.html web/mobile.html web/mobile.js tests/first_run.test.cjs tests/mobile.test.cjs tests/workspace.test.cjs
python -m unittest discover -s tests -p 'test_*.py'
python e2e/runner.py --all
node --test tests/first_run.test.cjs tests/mobile.test.cjs tests/workspace.test.cjs
node --check app.js
node --check graph3d.js
node --check features-ui.js
```

On Windows release work, also run the existing CI-equivalent `build_release.ps1`, `doctor` on the generated executable, and `tests/smoke_release.py`.

## Session log

- 2026-11-17 — Session 5 completed: the dashboard's Refresh action now reloads indexed repositories before selecting and loading a graph, including the transition from zero to one repository. The empty state gives an explicit `add` command and refresh action; a successfully indexed repository with no knowledge nodes points to Search and a bounded `context` command, rather than implying indexing failed. Generic graph failures offer a retry without rendering server error text that may contain a local path. README now distinguishes the code index from knowledge nodes. Three new browser-free runtime regressions run in both CI workflows. Verification: 304 Python tests (11 skipped), 209 E2E tests, 20 Node tests, Black (80 files), Prettier, `node --check app.js`, and `git diff --check` passed. An isolated loopback server and temporary repository confirmed empty projects, `add`, repository discovery, empty graph, and a working `context` call. **Remaining risks:** Chromium could not launch in this sandbox (`socket() failed: Operation not permitted`), so visual and real keyboard/browser behavior remain unverified; Windows release CI has not yet run for this change. **Exact next task:** Session 6 — add a reproducible local performance fixture that records corpus size, cold/warm indexing, retrieval latency, platform and memory without network/model calls, with validated machine-readable output and a documented command.

- 2026-11-17 — Session 4 completed: restored the desktop setup page's native `main` landmark, gave phone panel headings programmatic focus targets, moved focus to newly selected panel content, and returned focus to Copy when the fallback dialog closes. Added static semantic checks for names, labels, landmarks and mobile panel targets, plus runtime tests for dynamic Copy labels and focus transitions. The normal and npm verification workflows now run both Node test files and check formatting of the mobile source. Local verification: 304 Python tests (11 skipped), 209 E2E tests, 17 Node tests, Black (80 files), Prettier, `node --check web/mobile.js`, and `git diff --check` passed. **Remaining risk:** these browser-free tests cannot prove screen-reader announcements, visual contrast, responsive behavior, or focus order in real browsers; no live device test was run. **Exact next task:** Session 5 — improve the first-run empty state so a user can get from `serve` to adding a repository and seeing a graph or bounded context, with a focused regression for the no-project path.

- 2026-11-17 — Session 3 completed: `.github/workflows/publish-npm.yml` now runs a read-only `verify` job on pull requests, manual dispatch, and version tags. It gates publication on Black, Prettier, Python unit/E2E, both Node test files, browser script syntax, npm staging and a dry-run pack. Only a version-tag push can enter `publish`, which depends on `verify`; `id-token: write` is scoped to that job. Local verification: 302 Python tests (11 skipped), 209 E2E tests, 16 Node tests, Black (79 files), Prettier, three `node --check` commands, workflow structure assertions, staged npm dry-run (36 files), and `git diff --check` passed. GitHub Actions run [44032715533](https://github.com/ArshitGupta01/TokSmart/actions/runs/44032715533) passed the new `verify` job and skipped `publish` on the PR; run [44032715530](https://github.com/ArshitGupta01/TokSmart/actions/runs/44032715530) passed Ubuntu and Windows checks, including Windows package smoke. PR #8 merged. **Remaining risk:** the actual npm trusted-publishing/OIDC handshake and tag-triggered job were not exercised; no package was published. **Exact next task:** Session 4 — add a focused accessibility regression for the desktop and phone primary controls, covering accessible names and keyboard/focus behavior, and wire it into CI.

- 2026-11-17 — Fresh stores now default to TokSmart while existing RepoMind/LazyToken databases stay discoverable; new client registrations use the `toksmart` key while existing `lazytoken` registrations are preserved. Updated first-run tests and public-facing Hugging Face/E2E wording. Removed the superseded `docs/REVIEW_FIXES.md` snapshot (recoverable in git); retained benchmark and migration records. Windows executable, launcher, installer root, and archive now use TokSmart; old manifests/markers remain readable for upgrades. Legacy receipt/schema identifiers and explicit compatibility aliases remain stable.

- 2026-11-17 — Follow-up: the release smoke test now invokes the actual `toksmart` launcher and CI artifact uses its new name. Explicit database deletion is constrained to the canonical TokSmart directory even if an older database is selected through the compatibility fallback; added a regression test. Corrected watcher, migration and public repository UI diagnostics. Local `python -m unittest discover -s tests -p 'test_*.py'` passed (300 tests, 11 skipped); `python -m black --check .` and `git diff --check` passed. The earlier local E2E suite passed 209 cases, and Node mobile/workspace tests passed 16. PR #5 merged the TokSmart identity and release naming changes. PR #6 fixed the two Windows lifecycle regressions (managed root detection and client cleanup) plus Windows short-path test comparison; both merged. GitHub Actions run 44003685415 passed on Ubuntu and Windows, including the Windows PyInstaller build, `TokSmart.exe doctor`, and `tests/smoke_release.py` (install, setup, update, rollback, uninstall). No public release was published. **Next task:** Session 3 — make the release publishing workflow depend on the complete verification gate, including mobile/Node checks, then validate its least-privilege permissions.

- 2026-11-16 — Planning audit completed. No product code was changed. Baseline verification is recorded above.

- 2026-11-17 — Session 1 completed. Added a machine-readable compatibility inventory covering LazyToken, RepoMind, and TheekHai/KnowledgeNetwork identifiers, separating supported aliases and migration contracts from user-facing defects. Added a schema/coverage regression test. Local execution was unavailable for this session; verify with `python -m unittest tests.test_brand_compatibility` and the full CI gate before release. At the time, Session 2 was the next task; see the later naming and Windows release entries above.

- 2026-11-17 — Documentation cleanup: refreshed README with desktop/phone scope, install options, evidence limits and documentation links; corrected current CLI names in migration/mobile instructions, the live phone banner and bundled Codex agent roles. Removed the superseded external-project comparison audit and a tracked generated ablation report with overstated claims. `benchmark/graph_ablation.py` now writes its synthetic report under ignored `benchmark/results/`. Historical pilot names remain in the measured record. Verification: 302 Python tests (11 skipped), 209 E2E tests, 16 Node tests, Black, Prettier, generated ablation output under ignored `benchmark/results/`, all local Markdown links, and `git diff --check` passed. **Next task:** Session 3 publish CI parity.
