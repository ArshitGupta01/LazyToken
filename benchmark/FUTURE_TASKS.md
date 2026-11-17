# Future matched task specifications

These are prepared fixtures for a future authorized agent comparison, not completed benchmarks. Use the same model, settings, task, safety rules and acceptance checks. Do not expose this document or acceptance tests to agents.

Create each arm in a new directory using `python benchmark/prepare_sessions.py <new-directory>`; add `--follow-up --memory none`, `--follow-up --memory current`, or `--follow-up --memory stale` for the follow-up variants. The project and its isolated database are separate children of that directory. Only the project directory is the agent workspace; configure the database only for the applicable TokSmart arm. The baseline gets no knowledge server. Run `python benchmark/session_acceptance.py <project>` for the initial task and add `--follow-up` for the second task, from outside the agent workspace. These commands prepare and check fixtures; they do not run agents.

## Multi-file: expiry handling

Use the initial fixture with separate session storage, authentication service and request handler modules, plus existing tests. Sessions have an optional expiry timestamp; an expired session is currently accepted. Ask the agent: "Reject expired sessions in the primary handler's authentication path, preserving valid sessions and existing unauthorized responses. A session expires at its expiry timestamp. Add focused tests." Independent acceptance checks cover expired, unexpired and missing expiry, the boundary timestamp and an unchanged store. Compare direct exploration with optional compact context; record which files and graph calls each arm used.

## Repeated task: approved lesson

The follow-up snapshot has the first handler fixed and the second still bypassing authentication. The preparer creates an approved, verified project lesson with indexed evidence for current and stale variants; the stale variant changes and resyncs an evidence file. Ask the agent: "Apply the existing session expiry rule to the secondary handler while preserving its response behavior. Add focused tests." Acceptance checks cover both handlers, timestamp boundaries and unchanged valid behavior. Compare a clean baseline against context retrieval with the approved lesson; include a separate stale variant and verify the agent can inspect current source. Never carry a database or session between arms.

## Recording and execution

Record snapshot and fixture hashes, task and arm identifiers, client and model settings, order, success and acceptance results, provider-reported input/output tokens, elapsed time, indexing cost, graph calls, retries and repeated file reads. Record unknown measurements as unknown. Save traces and failed attempts separately. Repeat and alternate order when separately authorized; do not interpret a single run as general savings. No agent tasks have been run for these specifications.
