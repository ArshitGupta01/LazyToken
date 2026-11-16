// Synthetic fixtures verify behavior; they are not model benchmark results.
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const { test } = require('node:test');
const vm = require('node:vm');
const metrics = require('../web/prompt-metrics.js');
const prompts = JSON.parse(readFileSync(join(__dirname, '../web/prompts.json'), 'utf8'));
const flush = () => new Promise((resolve) => setImmediate(resolve));

function fixtureRuns() {
  return ['normal', 'lite', 'pro'].map((mode, index) => ({
    run_id: `fixture-${mode}`,
    experiment_id: 'fixture-only',
    task_id: 'case-1',
    trial: 1,
    mode,
    model: 'fixture-model',
    provider: 'fixture-provider',
    prompt_version: '1',
    prompt_sha: `fixture-sha-${mode}`,
    settings: { temperature: 0.2 },
    tools: [],
    status: 'success',
    usage_source: 'provider',
    input_tokens: 100,
    output_tokens: 50 - index * 10,
    total_tokens: 150 - index * 10,
    elapsed_seconds: 1 + index,
    cost: 0.001,
    task: 'Fixture task',
    context: [],
    followups: [],
    expected: 'Fixture expectation',
    response: 'Fixture response, not a measured model response',
    evaluation: {
      kind: 'manual',
      evaluator: 'human',
      scores: Object.fromEntries(metrics.criteria.map((key) => [key, 8])),
      notes: 'Fixture score'
    }
  }));
}
const report = (runs = fixtureRuns()) => ({ schema: 'toksmart-prompt-benchmark-v1', runs });

class Element {
  constructor(tag = 'div') {
    this.tag = tag;
    this.children = [];
    this.attributes = {};
    this.listeners = {};
    this.dataset = {};
    this.style = {};
    this.hidden = false;
    this.disabled = false;
    this.open = false;
    this.value = '';
    this.textContent = '';
  }
  append(...nodes) {
    this.children.push(...nodes);
  }
  replaceChildren(...nodes) {
    this.children = nodes;
  }
  setAttribute(key, value) {
    this.attributes[key] = value;
  }
  addEventListener(event, listener) {
    this.listeners[event] = listener;
  }
  showModal() {
    this.open = true;
  }
  close() {
    this.open = false;
  }
  focus() {
    this.focused = true;
  }
  select() {
    this.selected = true;
  }
  remove() {}
  click() {
    return this.listeners.click?.();
  }
}

function setup({
  denyClipboard = false,
  failFetch = false,
  saved = new Map(),
  denyStorage = false
} = {}) {
  const nodes = new Map();
  const node = (id) => {
    if (!nodes.has(id)) nodes.set(id, new Element());
    return nodes.get(id);
  };
  const tabs = ['prompts', 'benchmarks', 'help'].map((name) => {
    const button = new Element('button');
    button.dataset.panel = name;
    return button;
  });
  const copied = [];
  const downloads = [];
  const context = {
    document: {
      getElementById: node,
      createElement: (tag) => new Element(tag),
      querySelectorAll: () => tabs,
      body: new Element('body')
    },
    navigator: {
      clipboard: {
        writeText: async (text) => {
          if (denyClipboard) throw Error('denied');
          copied.push(text);
        }
      }
    },
    fetch: async () => {
      if (failFetch) throw Error('offline');
      return { ok: true, json: async () => prompts };
    },
    localStorage: {
      getItem: (key) => {
        if (denyStorage) throw Error('denied');
        return saved.get(key) || null;
      },
      setItem: (key, value) => {
        if (denyStorage) throw Error('denied');
        saved.set(key, value);
      },
      removeItem: (key) => {
        saved.delete(key);
      }
    },
    window: { scrollTo() {}, confirm: () => false },
    TokSmartMetrics: metrics,
    URL: {
      createObjectURL: (blob) => {
        downloads.push(blob);
        return 'blob:fixture';
      },
      revokeObjectURL() {}
    },
    Blob,
    setTimeout() {},
    Date
  };
  vm.runInNewContext(readFileSync(join(__dirname, '../web/mobile.js'), 'utf8'), context);
  const importReport = async (data) => {
    const target = node('benchmark-file');
    target.files = [{ size: JSON.stringify(data).length, text: async () => JSON.stringify(data) }];
    await target.listeners.change({ target });
  };
  return { node, tabs, copied, saved, context, downloads, importReport };
}

test('each of the three modes has one copy button using the exact canonical prompt', async () => {
  const page = setup();
  await flush();
  const cards = page.node('prompt-cards').children;
  assert.equal(cards.length, 3);
  for (const [index, mode] of ['lite', 'pro', 'coding'].entries()) {
    const buttons = cards[index].children.filter((node) => node.tag === 'button');
    assert.equal(buttons.length, 1);
    await buttons[0].click();
    assert.equal(page.copied[index], prompts.modes[mode].prompt);
  }
  assert.match(page.node('copy-status').textContent, /Copied/);
});

test('clipboard denial reveals selected prompt and failure to load is retryable', async () => {
  const page = setup({ denyClipboard: true });
  await flush();
  await page
    .node('prompt-cards')
    .children[0].children.find((n) => n.tag === 'button')
    .click();
  assert.equal(page.node('copy-fallback').open, true);
  assert.equal(page.node('fallback-text').value, prompts.modes.lite.prompt);
  assert.equal(page.node('fallback-text').selected, true);
  page.node('close-fallback').click();
  assert.equal(page.node('copy-fallback').open, false);
  const failed = setup({ failFetch: true });
  await flush();
  assert.equal(failed.node('retry-prompts').hidden, false);
  assert.equal(failed.node('prompt-cards').attributes['aria-busy'], 'false');
});

test('navigation updates the selected section and touch-friendly button state', async () => {
  const page = setup();
  page.tabs[1].click();
  assert.equal(page.node('benchmarks-panel').hidden, false);
  assert.equal(page.node('prompts-panel').hidden, true);
  assert.equal(page.tabs[1].attributes['aria-pressed'], 'true');
  page.tabs[2].click();
  assert.equal(page.node('help-panel').hidden, false);
  assert.equal(page.tabs[1].attributes['aria-pressed'], 'false');
});

test('benchmark imports persist, deduplicate, export and require reset confirmation', async () => {
  const page = setup();
  await page.importReport(report());
  assert.equal(page.saved.size, 1);
  assert.equal(page.node('export-json').disabled, false);
  await page.importReport(report());
  assert.equal(JSON.parse([...page.saved.values()][0]).runs.length, 3);
  const reloaded = setup({ saved: page.saved });
  assert.match(reloaded.node('benchmark-status').textContent, /Loaded/);
  page.node('export-json').click();
  assert.equal(JSON.parse(await page.downloads[0].text()).runs.length, 3);
  page.node('export-csv').click();
  assert.match(await page.downloads[1].text(), /input_tokens/);
  page.node('reset-history').click();
  assert.equal(page.saved.size, 1);
  page.context.window.confirm = () => true;
  page.node('reset-history').click();
  assert.equal(page.saved.size, 0);
});

test('invalid or conflicting imports preserve stored history', async () => {
  const page = setup();
  await page.importReport(report());
  const before = [...page.saved.values()][0];
  const changed = report();
  changed.runs[0].response = 'different';
  await page.importReport(changed);
  assert.match(page.node('benchmark-status').textContent, /Import failed/);
  assert.equal([...page.saved.values()][0], before);
  await page.importReport({ runs: [] });
  assert.equal([...page.saved.values()][0], before);
  const blocked = setup({ denyStorage: true });
  await blocked.importReport(report());
  assert.match(blocked.node('benchmark-status').textContent, /Import failed/);
});

test('metrics include input overhead, correct savings and quality differences', () => {
  const summary = metrics.summarize(report());
  assert.equal(summary.tokens, 420);
  assert.equal(summary.groups.length, 1);
  const pro = summary.groups[0].arms[2];
  assert.equal(pro.total, 130);
  assert.equal(pro.quality, 8);
  assert.equal(pro.qualityDifference, 0);
  assert.ok(Math.abs(pro.savings - (20 / 150) * 100) < 1e-10);
  assert.equal(pro.costSavings, 0);
});

test('failed, incomplete, mismatched model, settings, tools and contexts cannot produce savings', () => {
  for (const change of [
    (r) => {
      r.status = 'failed';
    },
    (r) => {
      r.usage_source = 'unknown';
    },
    (r) => {
      r.model = 'other-model';
    },
    (r) => {
      r.settings = { temperature: 0.9 };
    },
    (r) => {
      r.tools = ['web'];
    },
    (r) => {
      r.context = [{ role: 'user', content: 'different' }];
    },
    (r) => {
      r.experiment_id = 'different';
    }
  ]) {
    const data = report();
    change(data.runs[2]);
    assert.equal(metrics.summarize(data).groups.length, 0);
  }
  const nested = report();
  nested.runs[0].settings = { extra: { temperature: 0.1 } };
  nested.runs[1].settings = { extra: { temperature: 0.2 } };
  nested.runs[2].settings = { extra: { temperature: 0.3 } };
  assert.equal(metrics.summarize(nested).groups.length, 0);
});

test('zero baselines and unknown scores remain unknown; invalid numbers are rejected', () => {
  const data = report();
  data.runs.forEach((r) => {
    r.input_tokens = 0;
    r.output_tokens = 0;
    r.total_tokens = 0;
    r.cost = 0;
    r.evaluation = null;
  });
  const group = metrics.summarize(data).groups[0];
  assert.equal(group.arms[1].savings, null);
  assert.equal(group.arms[1].costSavings, null);
  assert.equal(group.arms[1].quality, null);
  const invalid = report();
  invalid.runs[0].total_tokens = 999;
  assert.throws(() => metrics.summarize(invalid), /token totals/);
  const duplicate = report();
  duplicate.runs.push(duplicate.runs[0]);
  assert.throws(() => metrics.summarize(duplicate), /duplicate run/);
});

test('mobile HTML uses existing components, local assets and no graph engine', () => {
  const html = readFileSync(join(__dirname, '../web/mobile.html'), 'utf8');
  assert.match(html, /href="styles.css"/);
  assert.match(html, /connect-card/);
  assert.match(html, /launch-btn/);
  assert.doesNotMatch(html, /graph3d|three\.module|features-ui|src="https:/);
  assert.match(html, /id="fallback-text"\s+readonly/);
  assert.match(html, /id="benchmark-file"/);
});

test('website, mobile page and local dashboard use the same logo', () => {
  const root = join(__dirname, '..');
  const logo = readFileSync(join(root, 'logo.svg'), 'utf8');
  assert.equal(readFileSync(join(root, 'web/logo.svg'), 'utf8'), logo);
  for (const name of ['index.html', 'web/index.html', 'web/mobile.html']) {
    const html = readFileSync(join(root, name), 'utf8');
    assert.match(html, /rel="icon" type="image\/svg\+xml" href="logo\.svg"/);
    assert.match(html, /class="toksmart-logo" src="logo\.svg"/);
  }
});

for (const device of [
  { userAgent: 'iPhone', platform: 'iPhone', maxTouchPoints: 5 },
  { userAgent: 'Android', platform: 'Linux arm', maxTouchPoints: 5 },
  { userAgent: 'Mozilla Macintosh', platform: 'MacIntel', maxTouchPoints: 5 }
]) {
  test(`mobile ${device.platform} routes to prompt hub without loopback polling`, () => {
    const listeners = {};
    const redirects = [];
    let requests = 0;
    vm.runInNewContext(readFileSync(join(__dirname, '../web/app.js'), 'utf8'), {
      document: {
        readyState: 'loading',
        addEventListener: (key, fn) => {
          listeners[key] = fn;
        },
        querySelectorAll: () => [],
        getElementById: () => null
      },
      window: { location: { replace: (url) => redirects.push(url), search: '' } },
      navigator: device,
      fetch: () => {
        requests++;
      },
      URLSearchParams,
      setInterval: () => {
        throw Error('Unexpected polling on mobile');
      }
    });
    listeners.DOMContentLoaded();
    assert.deepEqual(redirects, ['mobile.html']);
    assert.equal(requests, 0);
  });
}
