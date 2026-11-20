const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const vm = require('node:vm');

for (const file of ['app.js', 'web/app.js']) {
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

test('hosted page opens the local dashboard even after a saved disconnect', async () => {
  const listeners = {};
  const redirects = [];
  const document = {
    readyState: 'loading',
    addEventListener: (name, fn) => {
      listeners[name] = fn;
    },
    querySelectorAll: () => [],
    getElementById: () => null
  };
  const window = { location: { replace: (url) => redirects.push(url) } };
  const context = {
    document,
    window,
    navigator: { maxTouchPoints: 0, userAgent: '' },
    localStorage: { getItem: () => 'true' },
    fetch: async (url, options) => {
      assert.equal(url, 'http://127.0.0.1:8765/api/health');
      assert.equal(options.targetAddressSpace, 'loopback');
      return { ok: true, json: async () => ({ service: 'toksmart' }) };
    },
    AbortController,
    setInterval: () => 1,
    setTimeout: () => 1,
    clearTimeout: () => {},
    URLSearchParams
  };
  vm.runInNewContext(readFileSync(join(__dirname, '..', 'web/app.js'), 'utf8'), context);
  listeners.DOMContentLoaded();
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(redirects, ['http://127.0.0.1:8765/']);
});
