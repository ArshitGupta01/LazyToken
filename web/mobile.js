(() => {
  'use strict';
  const get = (id) => document.getElementById(id);
  const el = (tag, text, className) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  };
  const status = get('copy-status');
  const historyKey = 'toksmart_prompt_benchmarks_v1';
  let history = { schema: 'toksmart-prompt-benchmark-v1', runs: [] };
  let copying = false;
  let fallbackOpener = null;

  async function copyPrompt(prompt, button) {
    if (copying) return;
    copying = true;
    button.disabled = true;
    try {
      try {
        await navigator.clipboard.writeText(prompt);
      } catch {
        const input = get('fallback-text');
        input.value = prompt;
        fallbackOpener = button;
        if (!get('copy-fallback').open) get('copy-fallback').showModal();
        input.focus();
        input.select();
        status.textContent = 'Use your device’s Copy action on the selected prompt.';
        return;
      }
      status.textContent = 'Copied. Paste into your AI assistant.';
      button.textContent = 'Copied';
      setTimeout(() => {
        button.textContent = 'Copy';
      }, 2000);
    } finally {
      button.disabled = false;
      copying = false;
    }
  }

  async function loadPrompts() {
    const cards = get('prompt-cards');
    cards.setAttribute('aria-busy', 'true');
    get('retry-prompts').hidden = true;
    try {
      const response = await fetch('prompts.json', { cache: 'no-cache' });
      if (!response.ok) throw Error('Unable to load');
      const data = await response.json();
      if (
        !data.version ||
        !['lite', 'pro', 'coding'].every((mode) =>
          ['name', 'best_for', 'prompt'].every(
            (key) => typeof data.modes?.[mode]?.[key] === 'string'
          )
        )
      ) {
        throw Error('Invalid prompt file');
      }
      cards.replaceChildren();
      ['lite', 'pro', 'coding'].forEach((mode) => {
        const item = data.modes[mode];
        const card = el('article', undefined, 'prompt-card');
        const heading = el('h2', item.name.replace(/^TokSmart /, ''));
        heading.id = `mode-${mode}-title`;
        card.setAttribute('aria-labelledby', heading.id);
        const button = el('button', 'Copy', 'launch-btn');
        button.type = 'button';
        button.setAttribute('aria-label', `Copy ${item.name} prompt`);
        button.addEventListener('click', () => copyPrompt(item.prompt, button));
        const details = el('details');
        details.append(el('summary', 'Read the prompt'), el('pre', item.prompt, 'prompt-preview'));
        card.append(heading, el('p', item.best_for), button, details);
        cards.append(card);
      });
      status.textContent = '';
    } catch {
      status.textContent = 'Prompts could not load. Check your connection and retry.';
      get('retry-prompts').hidden = false;
    } finally {
      cards.setAttribute('aria-busy', 'false');
    }
  }

  document.querySelectorAll('[data-panel]').forEach((button) => {
    button.addEventListener('click', () => {
      const selected = button.dataset.panel;
      document.querySelectorAll('[data-panel]').forEach((tab) => {
        tab.setAttribute('aria-pressed', String(tab === button));
        get(`${tab.dataset.panel}-panel`).hidden = tab.dataset.panel !== selected;
      });
      get(
        { prompts: 'pocket-title', benchmarks: 'benchmarks-title', help: 'help-title' }[selected]
      ).focus({
        preventScroll: true
      });
      window.scrollTo({ top: 0, behavior: 'auto' });
    });
  });
  get('copy-fallback').addEventListener('close', () => {
    fallbackOpener?.focus();
    fallbackOpener = null;
  });
  get('close-fallback').addEventListener('click', () => get('copy-fallback').close());
  get('retry-prompts').addEventListener('click', loadPrompts);

  const fmt = (value, digits = 1) =>
    value === null
      ? 'Not measured'
      : value.toLocaleString(undefined, { maximumFractionDigits: digits });
  function bars(parent, title, arms, field, maximum, suffix = '') {
    parent.append(el('h4', title));
    arms.forEach((arm) => {
      const row = el('div', undefined, 'bar-row');
      const label = el('div', undefined, 'bar-label');
      const value = field === 'tokens' ? arm.total : arm[field];
      label.append(el('span', arm.mode), el('span', fmt(value) + (value === null ? '' : suffix)));
      const track = el('div', undefined, 'bar-track');
      const bar = el('span', undefined, field === 'quality' ? 'quality-bar' : '');
      bar.style.width = `${maximum > 0 && value !== null ? Math.min(100, Math.max(0, ((field === 'tokens' ? arm.input : value) / maximum) * 100)) : 0}%`;
      track.append(bar);
      if (field === 'tokens') {
        const output = el('span', undefined, 'output-bar');
        output.style.width = `${maximum > 0 ? (arm.output / maximum) * 100 : 0}%`;
        track.append(output);
      }
      row.append(label, track);
      parent.append(row);
    });
  }

  function renderHistory() {
    const filter = get('benchmark-category');
    const selectedCategory = filter.value || '';
    filter.replaceChildren();
    const all = el('option', 'All categories');
    all.value = '';
    filter.append(all);
    [...new Set(history.runs.map((run) => run.category || 'uncategorized'))]
      .sort()
      .forEach((category) => {
        const option = el('option', category.replaceAll('_', ' '));
        option.value = category;
        filter.append(option);
      });
    filter.value = selectedCategory;
    const selectedRuns = selectedCategory
      ? history.runs.filter((run) => (run.category || 'uncategorized') === selectedCategory)
      : history.runs;
    const summary = TokSmartMetrics.summarize({ ...history, runs: selectedRuns });
    const container = get('benchmark-results');
    container.replaceChildren();
    const metrics = el('div', undefined, 'metric-grid');
    for (const [label, value] of [
      ['Stored runs', summary.totalRuns],
      ['Measured tokens', summary.tokens],
      ['Failed runs', summary.failed],
      ['Matched trials', summary.groups.reduce((n, g) => n + g.pairs, 0)]
    ]) {
      const card = el('div', undefined, 'metric');
      card.append(el('strong', fmt(value, 0)), el('span', label));
      metrics.append(card);
    }
    container.append(metrics);
    for (const group of summary.groups) {
      const section = el('section', undefined, 'benchmark-group');
      section.append(
        el('h3', group.model),
        el(
          'p',
          `Experiment ${group.experiment} · ${group.pairs} complete matched trials`,
          'bench-caption'
        )
      );
      const knownQuality = group.arms.filter((arm) => arm.quality !== null);
      if (knownQuality.length) {
        const baselineQuality = group.arms[0].quality;
        const best = group.arms
          .filter((arm) => arm.quality >= baselineQuality)
          .sort((a, b) => a.total - b.total)[0];
        section.append(
          el(
            'p',
            `Lowest-token mode meeting Normal’s mean quality score: ${best.mode}. Descriptive result only; review individual accuracy and completeness scores.`,
            'bench-caption'
          )
        );
      } else {
        section.append(
          el(
            'p',
            'Best-performing mode: not determined until comparable quality evaluations are available.',
            'bench-caption'
          )
        );
      }
      bars(
        section,
        'Average tokens · purple: input / green: output',
        group.arms,
        'tokens',
        Math.max(...group.arms.map((a) => a.total))
      );
      bars(
        section,
        `Average quality / 10 · ${group.qualityPairs} matched scored trials`,
        group.arms,
        'quality',
        10
      );
      bars(
        section,
        'Average response time',
        group.arms,
        'seconds',
        Math.max(...group.arms.map((a) => a.seconds)),
        ' s'
      );
      bars(
        section,
        `Estimated API cost (USD) · ${group.costPairs} matched priced trials`,
        group.arms,
        'cost',
        Math.max(...group.arms.map((a) => a.cost || 0)),
        ' USD'
      );
      for (const arm of group.arms.slice(1)) {
        section.append(
          el(
            'p',
            `${arm.mode}: ${fmt(arm.savings)}% token savings; quality difference ${fmt(arm.qualityDifference)}; cost savings ${fmt(arm.costSavings)}${arm.costSavings === null ? '' : '%'}.`,
            'bench-caption'
          )
        );
      }
      container.append(section);
    }
    if (history.runs.length && !summary.groups.length)
      container.append(
        el(
          'p',
          'No complete, compatible Normal/Lite/Pro trials with provider-reported usage. Partial, failed and incompatible runs are excluded from savings.',
          'mobile-note'
        )
      );
    const details = el('details', undefined, 'mobile-guide');
    details.append(el('summary', 'View individual responses and evaluation notes'));
    // Keep large imports responsive; all runs remain in the exports.
    selectedRuns
      .slice(-100)
      .reverse()
      .forEach((run) => {
        const item = el('details', undefined, 'run-details');
        item.append(
          el('summary', `${run.task_id} · trial ${run.trial} · ${run.mode} · ${run.status}`),
          el(
            'p',
            `Model: ${run.model}. Provider: ${run.provider}. Time: ${fmt(run.elapsed_seconds)} s. Tokens: ${run.usage_source === 'provider' ? run.total_tokens : 'unknown'}.`
          ),
          el('h4', 'Task'),
          el('pre', run.task || ''),
          el('h4', 'Response'),
          el('pre', run.response || run.error || ''),
          el(
            'p',
            `Quality: ${run.evaluation ? `${run.evaluation.kind === 'ai' ? 'AI evaluation' : 'Manual evaluation'} ${JSON.stringify(run.evaluation.scores)}. ${run.evaluation.notes || ''}` : 'Not evaluated'}`
          )
        );
        details.append(item);
      });
    if (selectedRuns.length > 100)
      details.append(el('p', 'Showing the latest 100 responses. Export includes every run.'));
    container.append(details);
    ['export-json', 'export-csv', 'reset-history'].forEach((id) => {
      get(id).disabled = history.runs.length === 0;
    });
  }

  get('benchmark-file').addEventListener('change', async (event) => {
    const file = event.target.files[0];
    if (!file) return;
    try {
      if (file.size > 4 * 1024 * 1024)
        throw Error('Choose a report smaller than 4 MB. Export a selected experiment if needed.');
      const incoming = JSON.parse(await file.text());
      TokSmartMetrics.summarize(incoming);
      const byId = new Map(history.runs.map((run) => [run.run_id, run]));
      for (const run of incoming.runs) {
        if (byId.has(run.run_id) && JSON.stringify(byId.get(run.run_id)) !== JSON.stringify(run))
          throw Error(
            'A stored run has changed. Clear browser history with confirmation before importing a corrected report.'
          );
        byId.set(run.run_id, run);
      }
      const next = { schema: incoming.schema, runs: [...byId.values()] };
      TokSmartMetrics.summarize(next);
      localStorage.setItem(historyKey, JSON.stringify(next));
      history = next;
      renderHistory();
      get('benchmark-status').textContent =
        'Imported and saved in this browser. Values come from your report; they are not independently authenticated. Quality scores are manual or AI evaluations, not objective truth.';
    } catch (error) {
      get('benchmark-status').textContent =
        `Import failed: ${error.message}. Existing history is unchanged.`;
    }
    event.target.value = '';
  });
  get('benchmark-category').addEventListener('change', renderHistory);

  function download(text, type, extension) {
    const url = URL.createObjectURL(new Blob([text], { type }));
    const link = el('a');
    link.href = url;
    link.download = `toksmart-benchmarks-${Date.now()}.${extension}`;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  get('export-json').addEventListener('click', () =>
    download(JSON.stringify(history, null, 2), 'application/json', 'json')
  );
  get('export-csv').addEventListener('click', () => {
    const fields = [
      'run_id',
      'experiment_id',
      'task_id',
      'trial',
      'mode',
      'model',
      'provider',
      'status',
      'input_tokens',
      'output_tokens',
      'total_tokens',
      'usage_source',
      'elapsed_seconds',
      'cost',
      'evaluation'
    ];
    const escape = (value) => {
      let text =
        value == null ? '' : typeof value === 'object' ? JSON.stringify(value) : String(value);
      if (/^[=+@\-\t\r]/.test(text)) text = "'" + text;
      return '"' + text.replaceAll('"', '""') + '"';
    };
    download(
      [
        fields.join(','),
        ...history.runs.map((run) => fields.map((key) => escape(run[key])).join(','))
      ].join('\r\n'),
      'text/csv',
      'csv'
    );
  });
  get('reset-history').addEventListener('click', () => {
    if (
      !window.confirm(
        'Clear benchmark reports saved in this browser? Export a copy first if you want to keep them.'
      )
    )
      return;
    try {
      localStorage.removeItem(historyKey);
      history = { schema: 'toksmart-prompt-benchmark-v1', runs: [] };
      renderHistory();
      get('benchmark-status').textContent =
        'Browser history cleared. Your computer’s benchmark database is unchanged.';
    } catch {
      get('benchmark-status').textContent =
        'Browser storage is unavailable. History was not cleared.';
    }
  });

  try {
    const saved = localStorage.getItem(historyKey);
    if (saved) {
      const parsed = JSON.parse(saved);
      TokSmartMetrics.summarize(parsed);
      history = parsed;
      get('benchmark-status').textContent = 'Loaded benchmark history saved in this browser.';
    }
  } catch {
    get('benchmark-status').textContent =
      'Saved history could not load. Browser storage may be unavailable; import requires working local storage.';
  }
  renderHistory();
  loadPrompts();
})();
