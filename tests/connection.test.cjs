const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const vm = require('node:vm');

for (const file of ['app.js']) {
  test(`${file} waits for a healthy server despite a saved connection`, async () => {
    const listeners = {};
    const classes = new Set();
    const classList = { add: (x) => classes.add(x), remove: (x) => classes.delete(x) };
    const document = {
      readyState: 'loading',
      documentElement: { classList },
      body: { classList },
      addEventListener: (name, fn) => {
        listeners[name] = fn;
      },
      querySelectorAll: () => [],
      getElementById: () => null
    };
    const window = { location: { protocol: 'http:', hostname: '127.0.0.1' } };
    const context = {
      document,
      window,
      navigator: { maxTouchPoints: 0, userAgent: '' },
      localStorage: { getItem: (key) => (key === 'toksmart_connected' ? 'true' : null) },
      fetch: () => Promise.reject(new Error('offline')),
      AbortController,
      setInterval: () => 1,
      setTimeout: () => 1,
      clearTimeout: () => {},
      URL,
      URLSearchParams
    };
    vm.runInNewContext(readFileSync(join(__dirname, '..', file), 'utf8'), context);
    listeners.DOMContentLoaded();
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(classes.has('server-connected'), false);
  });
}
for (const file of ['app.js']) {
  test(`${file} verifies health and honors a disconnect during polling`, async () => {
    const listeners = {};
    const classes = new Set();
    const classList = { add: (x) => classes.add(x), remove: (x) => classes.delete(x) };
    const document = {
      readyState: 'loading',
      documentElement: { classList },
      body: { classList },
      addEventListener: (name, fn) => {
        listeners[name] = fn;
      },
      querySelectorAll: () => [],
      getElementById: () => null
    };
    const window = { location: { protocol: 'http:', hostname: '127.0.0.1' } };
    let poll;
    const context = {
      document,
      window,
      navigator: { maxTouchPoints: 0, userAgent: '' },
      localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
      fetch: async () => ({ ok: true, json: async () => ({ service: 'toksmart' }) }),
      AbortController,
      setInterval: (callback) => {
        poll = callback;
        return 1;
      },
      setTimeout: () => 1,
      clearTimeout: () => {},
      URL,
      URLSearchParams
    };
    vm.runInNewContext(readFileSync(join(__dirname, '..', file), 'utf8'), context);
    let started = false;
    window.startDashboard = () => {
      started = true;
    };
    listeners.DOMContentLoaded();
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(started, true);
    assert.equal(classes.has('server-connected'), true);

    let finishPoll;
    context.fetch = () => new Promise((resolve) => (finishPoll ??= resolve));
    const pending = poll();
    context.fetch = async () => ({ ok: true, json: async () => ({ service: 'toksmart' }) });
    listeners.click({
      target: { id: 'disconnect-btn' },
      preventDefault() {},
      stopPropagation() {}
    });
    finishPoll({ ok: true, json: async () => ({ service: 'toksmart' }) });
    await pending;
    assert.equal(classes.has('server-connected'), false);
  });
}

function hostedSetup(fetch) {
  const listeners = {};
  const elements = new Map();
  const redirects = [];
  let poll;
  const element = (id) => {
    if (!elements.has(id)) {
      elements.set(id, {
        dataset: {},
        textContent: '',
        href: id === 'open-dashboard' ? 'http://127.0.0.1:8765/' : undefined,
        setAttribute(name, value) {
          this[name] = value;
        },
        removeAttribute(name) {
          delete this[name];
        },
        addEventListener: (name, handler) => {
          listeners[id + ':' + name] = handler;
        }
      });
    }
    return elements.get(id);
  };
  const document = {
    readyState: 'loading',
    addEventListener: (name, listener) => {
      listeners[name] = listener;
    },
    getElementById: element
  };
  const window = { location: { assign: (url) => redirects.push(url) } };
  const context = {
    document,
    window,
    navigator: { maxTouchPoints: 0, userAgent: '' },
    fetch: (url, options) => {
      assert.equal(url, 'http://127.0.0.1:8765/api/health');
      assert.equal(options.targetAddressSpace, 'loopback');
      return fetch();
    },
    performance: { now: () => 5 },
    AbortController,
    setInterval: (callback) => {
      poll = callback;
    },
    setTimeout: () => 1,
    clearTimeout: () => {},
    URLSearchParams
  };
  vm.runInNewContext(readFileSync(join(__dirname, '..', 'web/app.js'), 'utf8'), context);
  listeners.DOMContentLoaded();
  return {
    element,
    redirects,
    retry: () => listeners['check-server:click'](),
    poll: () => poll(),
    copyLaunch: () => listeners['toksmart:launch-copied'](),
    enableAutoOpen() {
      element('auto-open').checked = true;
      listeners['auto-open:change']();
    }
  };
}

test('hosted setup reports readiness and latency after the server starts, then resumes waiting', async () => {
  let alive = false;
  let requests = 0;
  const setup = hostedSetup(async () => {
    requests++;
    if (!alive) throw new Error('offline');
    return {
      ok: true,
      json: async () => ({ status: 'ok', service: 'toksmart', version: '0.5.4' })
    };
  });
  const { element } = setup;
  assert.equal(element('check-server').disabled, true);
  await setup.retry();
  assert.equal(requests, 1);
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(element('server-state').textContent, 'Waiting for server');
  assert.equal(element('server-ping').textContent, '—');
  assert.equal(element('check-server').disabled, false);
  assert.equal(element('launch-step-run')['aria-current'], 'step');
  setup.copyLaunch();
  assert.equal(element('launch-step-connect')['aria-current'], 'step');
  assert.equal(element('launch-step-run').dataset.progress, 'complete');

  alive = true;
  await setup.retry();
  assert.equal(element('server-status').dataset.state, 'online');
  assert.equal(element('server-state').textContent, 'Server ready');
  assert.match(element('server-detail').textContent, /0\.5\.4/);
  assert.equal(element('server-ping').textContent, '<1 ms');
  assert(element('server-checked').textContent);
  assert.deepEqual(setup.redirects, []);
  assert.equal(element('launch-step-open')['aria-current'], 'step');
  assert.equal(element('launch-step-connect').dataset.progress, 'complete');

  alive = false;
  setup.poll();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(element('server-state').textContent, 'Waiting for server');
  assert.equal(element('server-ping').textContent, '—');
  assert.equal(element('launch-step-connect')['aria-current'], 'step');
});

test('hosted setup rejects a response from a different local service', async () => {
  const { element } = hostedSetup(async () => ({
    ok: true,
    json: async () => ({ status: 'ok', service: 'unrelated' })
  }));
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(element('server-status').dataset.state, 'unexpected');
  assert.equal(element('server-ping').textContent, '—');
});

test('opt-in opens only after a verified health response and is consumed once', async () => {
  let service = 'unrelated';
  const setup = hostedSetup(async () => ({
    ok: true,
    json: async () => ({ status: 'ok', service })
  }));
  await new Promise((resolve) => setImmediate(resolve));
  setup.enableAutoOpen();
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(setup.redirects, []);
  assert.equal(setup.element('auto-open').checked, true);

  service = 'toksmart';
  await setup.retry();
  assert.deepEqual(setup.redirects, ['http://127.0.0.1:8765/']);
  assert.equal(setup.element('auto-open').checked, false);
  await setup.retry();
  assert.deepEqual(setup.redirects, ['http://127.0.0.1:8765/']);
});
