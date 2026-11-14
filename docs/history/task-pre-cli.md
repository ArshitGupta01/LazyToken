# LazyToken — Final Product Roadmap & Task Backlog

> **Version:** Final roadmap v3.0\
> **Updated:** 2026-11-14\
> **Project name:** **LazyToken**\
> **Current pilot base:** `D:\LazyToken\`\
> **Current shared database:** `%LOCALAPPDATA%\TheekHai\KnowledgeNetwork\network.sqlite3`\
> **Primary goal:** **Maximum possible total token savings per successfully completed AI coding task**, without hurting correctness, security, maintainability, or developer control.\
> **Product promise:** **Install LazyToken once. It should work as an all-in-one local-first product.** End users should not need to separately install Ponytail, Serena, Code-Graph-RAG, a vector DB, a graph DB, a separate local web app, or a stack of companion tools just to get the main value.

---

## 1. Final product vision

**LazyToken** is a **local-first memory + context engine for AI coding assistants**.

It should help coding assistants:
- reuse verified project knowledge,
- avoid repeated discovery,
- retrieve only the smallest useful amount of context,
- prefer existing code over generating unnecessary code,
- and measurably reduce total token usage across real development tasks.

### One-line positioning

> **LazyToken is the all-in-one local context and memory layer that helps AI coding agents complete real coding tasks using fewer total tokens.**

### Core product principles

- **Token savings are the main KPI.**
- **Total task efficiency matters more than single-tool output size.**
- **Coding quality must not regress.**
- **Project isolation must remain strict.**
- **Everything important should work from one LazyToken installation.**
- **The system should be explainable, measurable, and local-first.**

---

## 2. What LazyToken already is based on the current pilot

These are from the supplied handoff and must be reverified against the actual repository code before being treated as fully confirmed implementation facts.

- [x] Python standard-library implementation.
- [x] Local SQLite-backed storage.
- [x] Shared reusable master asset graph.
- [x] Project-specific code indexes.
- [x] Weighted evidence-backed relationships.
- [x] Deterministic spreading activation up to two hops.
- [x] Separate project scope and global scope support.
- [x] Incremental sync behavior.
- [x] MCP stdio server.
- [x] Existing tool set including sync, search, graph inspection, recording assets/links, and token reporting.
- [x] TheekHai pilot data and tests already exist.

### Baseline preservation requirements

- [ ] Re-audit the current repository and verify what is actually implemented.
- [ ] Preserve unrelated uncommitted changes.
- [ ] Preserve the existing SQLite database.
- [ ] Back up user configs before migrations.
- [ ] Do not claim proposed features are already implemented.

---

## 3. Final non-negotiable product requirements

### 3.1 End-user experience

- [ ] A user should install **LazyToken** once and get the core value immediately.
- [ ] No required separate install of Ponytail.
- [ ] No required separate install of Serena.
- [ ] No required separate install of Code-Graph-RAG.
- [ ] No required separate install of Node.js, Docker, Python, or a browser-based build pipeline on end-user machines for the packaged release.
- [ ] The packaged release should include the runtime, the local server/backend, the database support, the dashboard assets, and the core retrieval logic.

### 3.2 Product behavior

- [ ] Work locally by default.
- [ ] Be able to function without internet for core indexing, graph exploration, and retrieval.
- [ ] Use strict project scoping to avoid knowledge leakage.
- [ ] Support explicit global reusable knowledge.
- [ ] Explain why context was retrieved.
- [ ] Track and display actual measured value wherever possible.

### 3.3 Token-efficiency contract

Every new feature must be judged by this standard:

> **Does it reduce total provider-reported tokens per successful task after counting its own overhead?**

If not, it does not count as a success.

---

## 4. The exact success metric

### Primary success metric

- **Lower total provider-reported tokens per successfully completed coding task**

### This must include

- input tokens,
- output tokens,
- reasoning tokens if available,
- cached input treatment when available,
- retries,
- tool call overhead,
- retrieval payloads,
- memory lookup overhead,
- and any context duplication.

### Secondary metrics

- task success rate,
- tests passed,
- correctness,
- security quality,
- latency,
- context relevance,
- cost per successful task,
- and ease of setup.

### Failure conditions

A feature does **not** count as successful if it:
- saves some retrieval tokens but increases retries,
- lowers correctness,
- worsens tests,
- causes stale or unsafe outputs,
- or adds too much MCP/tool overhead.

---

## 5. Highest-priority product capabilities

## P0 — Must-have for proving real token savings

### P0-01 — End-to-end benchmark system

Build this first.

- [x] Create a benchmark corpus of at least 20–30 realistic coding tasks.
- [x] Use TheekHai plus at least one unrelated project.
- [x] Include bug fixing, feature edits, repeated investigation, task continuation after compaction, and cross-project transfer.
- [ ] Compare at least:
  - baseline agent only,
  - current LazyToken,
  - improved LazyToken,
  - Ponytail as a research comparison arm,
  - and optionally LazyToken + Ponytail as a research-only combined arm.
- [ ] Record provider-reported tokens whenever possible.
- [ ] Record total cost, time, success rate, retries, and test outcomes.
- [x] Export JSON/CSV benchmark results.
- [x] Separate estimates from real provider numbers.

### P0-02 — Context Broker

This becomes the main intelligence layer.

- [x] Introduce a primary task-aware retrieval function such as `get_task_context`.
- [ ] Accept explicit token budgets.
- [x] Return ranked, deduplicated, relevance-explained results.
- [x] Start with tiny context breadcrumbs, not source dumps.
- [x] Allow progressive expansion only when needed.
- [x] Support compact / balanced / deep modes.
- [x] Return an abstain/no-confident-match outcome when appropriate.
- [x] Respect strict project isolation.

### P0-03 — Zero-retrieval decision mode

This is critical for best possible token savings.

- [ ] Detect when a task does **not** need graph or memory retrieval.
- [ ] Skip unnecessary retrieval for simple tasks.
- [ ] Prefer lightweight file-level context when sufficient.
- [ ] Measure the difference between retrieve vs skip decisions.

### P0-04 — Session-aware context deduplication

- [x] Track what context has already been supplied in the active task/session.
- [x] Avoid repeating the same summaries or graph results.
- [x] Avoid resending identical evidence unless explicitly requested.
- [ ] Compress updates relative to already-sent context.

### P0-05 — Adaptive retrieval budgets

- [ ] Budget should vary by task complexity.
- [ ] Small tasks should get very small initial retrievals.
- [ ] Complex tasks may get expanded progressively.
- [ ] Budgeting should optimize net token savings, not just response size.

### P0-06 — Retrieval quality evaluation

- [ ] Measure recall@k, precision@k, MRR or nDCG.
- [ ] Measure abstention quality.
- [ ] Evaluate total retrieved tokens.
- [ ] Compare lexical, symbol, graph, and hybrid ranking.
- [ ] Verify whether one-hop and two-hop expansion helps or hurts.

### P0-07 — Built-in coding-efficiency policy

Inspired by Ponytail principles, but owned by LazyToken.

- [x] Reuse-before-create policy.
- [x] Prefer minimal safe diffs.
- [x] Avoid unnecessary new dependencies.
- [x] Preserve security and validation.
- [x] Encourage test discipline.
- [x] Prefer existing project capabilities before inventing new layers.
- [ ] Offer built-in review and audit flows.

### P0-08 — Automatic memory proposals

- [x] Propose reusable lessons after tasks.
- [x] Require approval before promotion.
- [x] Capture problem, attempted approaches, successful resolution, affected files, and evidence.
- [x] Distinguish verified, stale, hypothesis, rejected, and superseded memories.
- [ ] Deduplicate similar memories.

---

## 6. P1 — Out-of-the-box product quality

### P1-01 — One-install packaged release

- [ ] Create a first-class Windows release artifact.
- [ ] Bundle the runtime and static frontend.
- [ ] Bundle backend/server functionality.
- [ ] Bundle dashboard UI assets.
- [ ] Bundle local SQLite support.
- [ ] Bundle core retrieval and indexing logic.
- [ ] Support install, backup, upgrade, rollback, and uninstall.

### P1-02 — Setup wizard / CLI

Planned commands, not current claims:

- [ ] `lazytoken init`
- [ ] `lazytoken doctor`
- [ ] `lazytoken add <repo>`
- [ ] `lazytoken sync`
- [ ] `lazytoken context`
- [ ] `lazytoken search`
- [ ] `lazytoken checkpoint`
- [ ] `lazytoken dashboard`
- [ ] `lazytoken benchmark`
- [ ] `lazytoken backup`
- [ ] `lazytoken restore`
- [ ] `lazytoken uninstall`

### P1-03 — Better code search, built in

- [ ] Improve path, declaration, and import search.
- [x] Add SQLite FTS5 where available.
- [ ] Improve identifier normalization and splitting.
- [ ] Add limited code dependency signals.
- [x] Add on-demand source range inspection.
- [ ] Add optional semantic search only if benchmarked benefit justifies it.

### P1-04 — Freshness and provenance system

- [x] Track source path, project, and evidence.
- [x] Track source hash or commit when available.
- [x] Mark dependent knowledge stale when supporting files change.
- [ ] Resolve conflicts explicitly.
- [x] Never present stale project knowledge as definitely current.

### P1-05 — Safe update detection and indexing

- [x] Incremental sync remains efficient.
- [x] Respect `.gitignore` and exclusions.
- [ ] Keep secret filtering strict.
- [x] Allow manual sync fallback.
- [ ] Support optional watcher behavior only if low overhead.

---

## 7. Visual interface plan — both 2D and 3D

LazyToken should have **both 2D and 3D graph experiences**.

### Final decision

- **2D mode** = default daily work mode.
- **3D mode** = optional immersive exploration mode.

### Why both?

#### 2D mode strengths
- better for daily use,
- easier to read,
- easier for debugging,
- lighter on performance,
- better for dense relationship inspection.

#### 3D mode strengths
- stronger wow factor,
- better product identity,
- better exploratory storytelling,
- visually impressive for demos,
- can help reveal cluster structure in a more immersive way.

### Product rule

- [ ] Neither 2D nor 3D mode should be required for agent operation.
- [ ] Visualization is for human understanding, debugging, trust, and product value.
- [ ] Visualization must not add token overhead to normal retrieval workflows.

---

## 8. Final visual design direction

The user preferred the **dark futuristic glowing network style**.

So LazyToken's visual identity should follow that direction.

### Final interface aesthetic

- dark background,
- futuristic technical mood,
- glowing cyan / blue / violet accents,
- soft neon edges and nodes,
- premium modern dashboard feel,
- immersive graph focus,
- readable but stylish information panels,
- clean technical typography,
- subtle animations,
- depth and atmosphere without clutter.

### Style keywords

- futuristic,
- cyber,
- dark tech,
- premium,
- glowing,
- immersive,
- neural-network-like,
- data constellation,
- graph intelligence,
- sci-fi dashboard.

---

## 9. Prompt/spec details for the visual interface

This section should guide actual image generation, concept generation, and UI prototyping.

### 9.1 Master creative direction prompt

Use this as the primary concept prompt for the dashboard aesthetic:

> **Design a futuristic dark-mode interface for LazyToken, a local-first AI coding memory and context engine focused on maximum token savings. Show an interactive knowledge graph as the centerpiece. The scene should feel like a premium technical dashboard with a black or very dark navy background, glowing cyan, electric blue, and violet nodes connected by luminous edges, subtle depth, soft bloom, floating panels, and a polished high-tech atmosphere. The interface should communicate intelligence, memory, project relationships, token analytics, and explainable context retrieval. Include a modern side panel or inspector for node details, a compact analytics section for token savings and retrieval stats, a search field, filters, and a graph-centric layout. The design should feel sleek, advanced, and production-grade, not like a game UI or a generic admin panel. Prioritize readability, visual hierarchy, and a striking graph centerpiece.**

### 9.2 2D dashboard concept prompt

> **Create a polished 2D dashboard UI concept for LazyToken. The main view is a force-directed knowledge graph on a dark background with glowing cyan, blue, and purple nodes and luminous connection lines. Around the graph, place elegant translucent panels for search, project filters, token analytics, memory status, and evidence inspection. Use clean typography, subtle glassmorphism, strong contrast, and a futuristic technical style. The interface should look premium, readable, and trustworthy, built for developers. Show categories such as projects, technologies, decisions, lessons, and symbols with clear visual differentiation. Include a right-side inspector panel showing node metadata, linked evidence, freshness state, and why the node was retrieved.**

### 9.3 3D explorer concept prompt

> **Create a premium 3D interactive interface concept for LazyToken where the knowledge graph appears like a floating constellation of glowing nodes in a dark digital space. Use cyan, blue, and violet light for nodes and edges, with subtle depth fog, ambient glow, and a futuristic sci-fi data-atlas feeling. The graph should feel immersive but organized, with clusters representing projects, technologies, decisions, and reusable knowledge. Include sleek UI overlays for search, filters, token metrics, and selected node details, while keeping the graph as the dominant visual focus. The design should feel advanced, elegant, and product-ready rather than decorative only.**

### 9.4 Motion and interaction prompt/spec

- [ ] Smooth pan and zoom.
- [ ] Drag nodes.
- [ ] Click to inspect node details.
- [ ] Hover highlights related edges and neighbors.
- [ ] Focus mode isolates local neighborhoods.
- [ ] Search should fly/focus to nodes.
- [ ] Subtle glow pulse animation for selected nodes.
- [ ] Reduced-motion mode must exist.

### 9.5 Visual hierarchy rules

- [ ] Graph remains the hero element.
- [ ] Side panels should support, not dominate.
- [ ] Analytics must be readable at a glance.
- [ ] Neon glow should be controlled and premium, not messy.
- [ ] Text readability must remain strong.
- [ ] Use clear contrast between verified, stale, and unverified states.

### 9.6 Node and edge style guidance

- [ ] Projects: larger cluster anchors.
- [ ] Technologies/assets: medium nodes.
- [ ] Decisions/lessons: distinctive icon or shape.
- [ ] Symbols/files: smaller nodes in dense clusters.
- [ ] Edge thickness reflects relationship strength.
- [ ] Edge style reflects global vs project-scoped relationship.
- [ ] Visual state for stale/unverified edges.

### 9.7 2D dashboard feature checklist

- [x] Search bar.
- [x] Project selector.
- [ ] Global vs project scope toggle.
- [x] Node type filter.
- [ ] Freshness/confidence filter.
- [x] Inspector panel.
- [ ] Token analytics panel.
- [ ] Explain retrieval panel.
- [x] Legend.
- [x] Empty-state handling.

### 9.8 3D explorer feature checklist

- [ ] Orbit/pan/zoom controls.
- [ ] Click-to-focus.
- [ ] Cluster highlighting.
- [ ] Search-and-fly-to-node behavior.
- [ ] Camera reset.
- [ ] Performance-safe rendering.
- [ ] Optional mini-map or overview.
- [ ] Overlay inspector.
- [ ] Toggle between immersive and simplified rendering.

### 9.9 Technical implementation direction

- [ ] Use the repository as the base.
- [x] Keep one shared data layer for both 2D and 3D visualizations.
- [x] 2D and 3D should read the same underlying graph state.
- [x] Keep the graph viewer local and bundled.
- [x] No CDN dependency for end users.
- [x] Serve locally via LazyToken backend.
- [x] Bind safely to localhost only.
- [x] Protect local endpoints appropriately.

### 9.10 Product recommendation

- [ ] Build 2D first for usability.
- [ ] Build 3D second for exploration and product identity.
- [ ] Reuse shared filtering, inspector, and search logic.
- [x] Keep 3D mode optional and on-demand.

---

## 10. Competitive strategy and Ponytail conclusion

### Final conclusion on Ponytail

Ponytail is a strong reference for coding-efficiency behavior, but LazyToken should **not** depend on users installing Ponytail.

### What LazyToken should adopt as first-party behavior

- reuse existing code first,
- avoid unnecessary dependencies,
- prefer minimal safe changes,
- maintain test discipline,
- encourage review and audit behavior,
- measure actual impact.

### What LazyToken should not do

- do not require Ponytail installation,
- do not market LazyToken as needing multiple helper tools,
- do not blindly copy without license compliance,
- do not make unsupported benchmark claims.

### Legal note

Ponytail uses the MIT License, so selective code reuse may be possible if done correctly with proper attribution and license compliance.

### Planned product rule

- [ ] If Ponytail code is reused, keep notices and license text as required.
- [ ] Prefer selectively reusing useful implementation patterns rather than blindly copying the entire project.
- [ ] Keep LazyToken positioned as its own independent product.

---

## 11. Security, privacy, and reliability requirements

- [ ] Enforce repository root boundaries.
- [ ] Prevent directory traversal.
- [ ] Respect secret exclusions.
- [ ] Prevent accidental inclusion of `.env`, keys, credentials, and sensitive files.
- [ ] Treat repository content and stored memory as untrusted for prompt-injection purposes.
- [ ] Use localhost-safe dashboard serving.
- [ ] Protect mutation endpoints.
- [ ] Provide backups and rollback.
- [ ] Support data deletion and export.
- [ ] Preserve user trust through explainability.

---

> **Current instruction:** Prepare measurement tools, but do not run real benchmark tasks until explicitly requested.

## 12. Final release milestones

### M0 — Integrity + measurement foundation
- [x] Audit current implementation.
- [ ] Verify existing features.
- [x] Create benchmark harness.
- [ ] Run baseline tasks.

### M1 — First token-efficient core
- [x] Implement Context Broker.
- [ ] Implement zero-retrieval decisions.
- [ ] Implement adaptive budgets.
- [x] Implement deduplication.
- [x] Implement retrieval evaluation.
- [x] Implement core coding-efficiency policy.

### M2 — Reliable memory and explainability
- [x] Implement task memory proposals.
- [x] Implement approval workflow.
- [x] Implement freshness/provenance.
- [x] Implement explain retrieval logic.

### M3 — Product experience
- [ ] Package Windows-first all-in-one build.
- [ ] Add setup wizard and CLI.
- [x] Add local dashboard.
- [x] Add 2D graph view.
- [ ] Add analytics panel.

### M4 — Visual differentiation
- [x] Add immersive 3D explorer.
- [x] Reuse shared data and controls.
- [ ] Tune performance and reduced-motion handling.
- [ ] Finalize product visual identity.

### M5 — Benchmark-backed product claims
- [ ] Run end-to-end comparisons.
- [ ] Publish honest measurements.
- [ ] Validate that improvements reduce total task tokens while preserving quality.

---

## 13. Immediate next implementation order

1. Audit the current repo and verify the pilot.
2. Build the benchmark harness.
3. Implement the Context Broker.
4. Add zero-retrieval mode and session deduplication.
5. Add adaptive budgeting.
6. Add built-in LazyToken coding-efficiency policy.
7. Add memory proposal and freshness system.
8. Build the 2D dashboard first.
9. Build the 3D explorer second using the same data model.
10. Package the all-in-one LazyToken release.

---

## 14. Final definition of “best possible token savings” for LazyToken

LazyToken achieves its mission only if it can do this:

- help assistants retrieve less unnecessary context,
- avoid re-discovering what is already known,
- avoid repeating the same context within a session,
- skip retrieval entirely when not needed,
- prefer existing code over unnecessary generation,
- and still complete tasks successfully.

### Final practical interpretation

> **Best possible token savings means minimizing total token consumption per successful coding task, not just returning smaller search results.**

That includes the cost of LazyToken itself.

---

## 15. Final product statement

> **LazyToken will be a local-first, all-in-one token-efficiency engine for AI coding assistants, combining verified memory, compact retrieval, reuse-first coding guidance, and an impressive 2D + 3D graph interface—while measuring whether it truly saves tokens in real development work.**

---

## 16. File placement and maintenance notes

- Repository location: `D:\LazyToken\task.md`
- This file is the current **final roadmap** based on the conversation and conclusions.
- Update checklist items only after implementation and verification.
- Keep the product name **LazyToken** everywhere.
- Use the repository as the implementation base.



## 17. Release hardening audit — 2026-11-14

See `AUDIT.md` and `IMPLEMENTATION_STATUS.md` for verified scope and limitations. Checked items describe existing implementations, not proof of measured token savings or universal device compatibility. Progressive retrieval uses explicit larger budgets/modes and session fingerprints. Completion learning is an explicit MCP/CLI checkpoint; automatic lifecycle hooks remain pending. Similar-memory detection is heuristic. Optional offline tokenizer enforces the compact JSON payload against the configured tokenizer, excluding transport/provider framing; default budgets remain estimates. Real benchmark execution stays unchecked and requires separate authorization. No push is authorized in this session.
