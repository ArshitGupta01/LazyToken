(() => {
  const panel = document.querySelector('#knowledge-workspace'),
    body = document.querySelector('#workspace-body'),
    scope = document.querySelector('#workspace-scope'),
    project = document.querySelector('#project');
  let current = 'search',
    token = '',
    generation = 0;
  const el = (tag, text, cls) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (cls) node.className = cls;
    return node;
  };
  function message(text) {
    body.replaceChildren(el('p', text, 'workspace-message'));
  }
  function projectName() {
    return project.selectedOptions[0]?.textContent || '';
  }
  async function request(action, extra = {}) {
    const apiBase = window.API_BASE || '';
    const query = new URLSearchParams({ action, project: project.value, ...extra });
    const r = await fetch(apiBase + '/api/lazytoken?' + query);
    const d = await r.json();
    if (!r.ok) throw Error(d.error || 'Unable to load');
    return d;
  }
  async function review(args) {
    const apiBase = window.API_BASE || '';
    const selectedProject = project.value;
    if (!token) {
      const response = await fetch(apiBase + '/api/session');
      token = (await response.json()).token;
    }
    const response = await fetch(apiBase + '/api/review', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-LazyToken-Review': token },
      body: JSON.stringify({ project: selectedProject, ...args })
    });
    const result = await response.json();
    if (!response.ok) throw Error(result.error || 'Review failed');
    return result;
  }
  function card(title, meta, description) {
    const box = el('article', undefined, 'workspace-card');
    box.append(el('h3', title), el('div', meta, 'workspace-meta'));
    if (description) box.append(el('p', description));
    body.append(box);
    return box;
  }
  async function render() {
    const requestGeneration = ++generation;
    const view = current;
    body.replaceChildren();
    scope.textContent = project.value
      ? 'Project: ' + projectName()
      : 'Select a project in the sidebar for search, review, and dependencies.';
    document
      .querySelectorAll('.workspace-nav button')
      .forEach((b) => b.classList.toggle('active', b.dataset.view === current));
    if (current === 'search') {
      if (!project.value) {
        message('Select a project to search its indexed metadata.');
        return;
      }
      const form = el('form', undefined, 'workspace-search');
      const input = el('input');
      input.placeholder = 'Search files, symbols, imports, and knowledge';
      input.setAttribute('aria-label', 'Search project knowledge');
      const button = el('button', 'Search');
      form.append(input, button);
      const results = el('div');
      body.append(form, results);
      form.onsubmit = async (e) => {
        e.preventDefault();
        const searchGeneration = ++generation;
        results.replaceChildren();
        try {
          const d = await request('search', { query: input.value });
          if (searchGeneration !== generation || panel.hidden) return;
          if (!d.results.length) {
            results.append(el('p', 'No matches found.'));
            return;
          }
          for (const item of d.results) {
            const box = el('article', undefined, 'workspace-card');
            box.append(
              el('h3', item.name || item.path),
              el(
                'div',
                `${item.type}${item.freshness ? ' · ' + item.freshness : ''}`,
                'workspace-meta'
              ),
              el('p', item.path || item.summary || '')
            );
            if (item.why) box.append(el('p', item.why, 'workspace-evidence'));
            results.append(box);
          }
        } catch (err) {
          if (searchGeneration === generation && !panel.hidden)
            results.append(el('p', err.message));
        }
      };
      return;
    }
    if (['proposals', 'dependencies'].includes(current) && !project.value) {
      message('Select a project to continue.');
      return;
    }
    message('Loading…');
    try {
      const d = await request(view);
      if (requestGeneration !== generation || panel.hidden) return;
      body.replaceChildren();
      if (view === 'proposals') {
        if (!d.proposals.length) {
          message(
            'No memory proposals for this project. Agents can submit them through the LazyToken MCP tool or CLI.'
          );
          return;
        }
        for (const p of d.proposals) {
          const c = card(
            p.name,
            `${p.kind} · ${p.status} · ${p.verification_state} · ${p.freshness} · confidence ${p.confidence}`,
            p.summary
          );
          c.append(el('p', 'Evidence: ' + p.evidence, 'workspace-evidence'));
          for (const field of ['problem', 'attempts', 'resolution'])
            if (p[field]) c.append(el('p', field + ': ' + p[field], 'workspace-evidence'));
          if (p.status === 'approved') {
            const supersede = el('button', 'Mark superseded');
            supersede.type = 'button';
            supersede.onclick = async () => {
              supersede.disabled = true;
              try {
                await review({ id: p.id, action: 'supersede' });
                await render();
              } catch (err) {
                c.append(el('p', err.message, 'workspace-warning'));
                supersede.disabled = false;
              }
            };
            c.append(supersede);
          }
          if (p.paths.length)
            c.append(
              el('p', 'Files: ' + p.paths.map((x) => x.path).join(', '), 'workspace-evidence')
            );
          if (p.changed_paths.length)
            c.append(el('p', 'Changed: ' + p.changed_paths.join(', '), 'workspace-warning'));
          if (p.status === 'approved' && p.freshness === 'stale') {
            const revalidate = el('button', 'Mark evidence reviewed');
            revalidate.type = 'button';
            revalidate.onclick = async () => {
              revalidate.disabled = true;
              try {
                await review({ id: p.id, action: 'revalidate' });
                await render();
              } catch (err) {
                c.append(el('p', err.message, 'workspace-warning'));
                revalidate.disabled = false;
              }
            };
            c.append(revalidate);
          }
          if (p.status === 'pending') {
            const verifyLabel = el('label', undefined, 'workspace-evidence');
            const verified = el('input');
            verified.type = 'checkbox';
            verifyLabel.append(
              verified,
              document.createTextNode(' I verified the current file evidence')
            );
            c.append(verifyLabel);
            const actions = el('div', undefined, 'workspace-actions');
            for (const [label, action] of [
              ['Approve', 'approve'],
              ['Reject', 'reject'],
              ['Edit', 'edit']
            ]) {
              const b = el('button', label);
              b.type = 'button';
              b.onclick = async () => {
                if (action === 'edit') {
                  const form = el('form', undefined, 'edit-memory');
                  const name = el('input');
                  name.value = p.name;
                  name.setAttribute('aria-label', 'Memory name');
                  const summary = el('textarea');
                  summary.value = p.summary;
                  summary.setAttribute('aria-label', 'Memory summary');
                  const evidence = el('textarea');
                  evidence.value = p.evidence;
                  evidence.setAttribute('aria-label', 'Memory evidence');
                  const save = el('button', 'Save changes');
                  form.append(name, summary, evidence, save);
                  actions.replaceWith(form);
                  form.onsubmit = async (e) => {
                    e.preventDefault();
                    save.disabled = true;
                    try {
                      await review({
                        id: p.id,
                        action: 'edit',
                        name: name.value,
                        summary: summary.value,
                        evidence: evidence.value
                      });
                      await render();
                    } catch (err) {
                      form.append(el('p', err.message, 'workspace-warning'));
                      save.disabled = false;
                    }
                  };
                  return;
                }
                b.disabled = true;
                try {
                  await review({ id: p.id, action, verified: verified.checked });
                  await render();
                } catch (err) {
                  c.append(el('p', err.message, 'workspace-warning'));
                  b.disabled = false;
                }
              };
              actions.append(b);
            }
            c.append(actions);
          }
        }
      } else if (view === 'benchmark_list') {
        body.append(
          el(
            'p',
            'No benchmark tasks are run automatically. Enter future measured runs through the CLI or MCP. Comparisons are unverified until matched runs and task outcomes are reviewed.',
            'workspace-message'
          )
        );
        for (const c of d.canonical?.comparisons || []) {
          card(
            c.task_id,
            `${c.arm} · ${c.measurement_kind} · ${c.comparable ? 'comparable' : 'not comparable'}`,
            c.comparable
              ? `Recorded token difference: ${c.tokens_saved}. Provider usage and outcomes are caller-reported.`
              : c.reasons.join('; ')
          );
        }
        if (!d.runs.length) {
          if (!d.canonical?.runs.length) body.append(el('p', 'No benchmark records yet.'));
          return;
        }
        for (const group of d.comparisons) {
          const v = (x) => (x === null || x === undefined ? 'Unknown' : String(x));
          const describe = (r) =>
            r
              ? `input ${v(r.input_tokens)}, output ${v(r.output_tokens)}, total ${v(r.total_tokens)}, time ${v(r.elapsed_seconds)} s, success ${v(r.successful)}, extra reads ${v(r.unnecessary_file_reads)}, indexing ${v(r.indexing_tokens)}`
              : 'not recorded';
          const c = card(
            group.task,
            `${group.model || 'Model unknown'} · Recorded difference (unverified): ${v(group.recorded_difference)}`,
            `Baseline: ${describe(group.baseline)}`
          );
          c.append(el('p', `Network: ${describe(group.network)}`));
          if (group.settings)
            c.append(el('p', `Settings: ${group.settings}`, 'workspace-evidence'));
        }
      } else if (view === 'dependencies') {
        if (!d.dependencies.length) {
          message('No imports recorded for this project.');
          return;
        }
        body.append(el('p', d.note, 'workspace-message'));
        for (const dep of d.dependencies)
          card(
            dep.import,
            dep.status,
            dep.source +
              (dep.candidates.length
                ? ' → ' + dep.candidates.map((c) => c.path + ':' + c.line).join(', ')
                : '')
          );
      } else {
        body.append(el('p', d.note, 'workspace-message'));
        if (!d.candidates.length) {
          body.append(el('p', 'No shared candidates yet.'));
          return;
        }
        for (const candidate of d.candidates) {
          const c = card(
            candidate.name,
            `${candidate.kind} · ${candidate.projects} projects`,
            candidate.summary
          );
          for (const source of candidate.evidence || [])
            c.append(
              el(
                'p',
                `${source.project_id}${source.summary ? ' · ' + source.summary : ''}`,
                'workspace-evidence'
              )
            );
        }
      }
    } catch (err) {
      if (requestGeneration === generation && !panel.hidden) message(err.message);
    }
  }
  function setNavigation(view) {
    document
      .querySelectorAll('[data-workspace-view]')
      .forEach((b) => b.classList.toggle('active', b.dataset.workspaceView === view));
  }
  function openWorkspace(view) {
    setNavigation(view);
    if (view === 'graph') {
      generation++;
      panel.hidden = true;
      return;
    }
    current = view;
    panel.hidden = false;
    render();
  }
  document.querySelector('#workspace-open').onclick = () => openWorkspace('search');
  document.querySelector('#workspace-close').onclick = () => {
    generation++;
    panel.hidden = true;
    setNavigation('graph');
  };
  document.querySelectorAll('.workspace-nav button').forEach(
    (b) =>
      (b.onclick = () => {
        current = b.dataset.view;
        setNavigation(current);
        render();
      })
  );
  document
    .querySelectorAll('[data-workspace-view]')
    .forEach((b) => (b.onclick = () => openWorkspace(b.dataset.workspaceView)));
  project.addEventListener('change', () => {
    if (!panel.hidden) render();
  });
  request('benchmark_list')
    .then((data) => {
      if (data.runs.length) {
        document.querySelector('#analytics-bench').textContent = 'Not verified';
        document.querySelector('#analytics-bench-note').textContent =
          `${data.runs.length} records loaded`;
      }
    })
    .catch(() => {
      document.querySelector('#analytics-bench').textContent = 'Unavailable';
      document.querySelector('#analytics-bench-note').textContent = 'Could not load records';
    });
})();
