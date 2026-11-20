const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const { test } = require('node:test');
const vm = require('node:vm');

function setup() {
  const elements = new Map();
  const element = (selector) => {
    if (!elements.has(selector)) {
      elements.set(selector, {
        hidden: false,
        value: '',
        textContent: '',
        dataset: {},
        classList: { toggle() {}, add() {}, remove() {} },
        parentElement: { clientWidth: 800, clientHeight: 500 },
        getContext: () => ({
          setTransform() {},
          clearRect() {},
          save() {},
          translate() {},
          scale() {},
          restore() {}
        }),
        addEventListener() {},
        querySelectorAll: () => [],
        setAttribute() {},
        getBoundingClientRect: () => ({ left: 0, top: 0, width: 800, height: 500 })
      });
    }
    return elements.get(selector);
  };
  const scopes = ['', '@workspace'].map((project) => ({
    dataset: { project },
    classList: { toggle() {} },
    setAttribute(name, value) {
      this[name] = value;
    }
  }));
  const requests = [];
  const document = {
    readyState: 'loading',
    querySelector: element,
    querySelectorAll: (selector) => (selector === '.scope' ? scopes : []),
    addEventListener() {}
  };
  const window = { location: { protocol: 'http:', hostname: '127.0.0.1' } };
  const context = {
    window,
    document,
    localStorage: { getItem: () => null },
    matchMedia: () => ({ matches: true }),
    devicePixelRatio: 1,
    ResizeObserver: class {
      observe() {}
    },
    requestAnimationFrame: (callback) => {
      setImmediate(callback);
      return 1;
    },
    cancelAnimationFrame() {},
    setInterval() {},
    fetch: (url) =>
      new Promise((resolve) => {
        requests.push({ url, reply: (data, ok = true) => resolve({ ok, json: async () => data }) });
      })
  };
  vm.runInNewContext(readFileSync(join(__dirname, '../app.js'), 'utf8'), context);
  window.startDashboard();
  return { element, requests, scopes };
}
const settle = () => new Promise((resolve) => setImmediate(resolve));

test('refresh discovers a repository added after first run and selects its graph', async () => {
  const html = readFileSync(join(__dirname, '../index.html'), 'utf8');
  assert.match(html, /id="empty-refresh"[^>]*>\s*Refresh projects\s*<\/button>/);
  assert.match(html, /id="empty-search"[^>]*>\s*Search indexed code\s*<\/button>/);
  assert.match(html, /add "ABSOLUTE_PATH_TO_REPOSITORY"/);
  const { element, requests } = setup();
  const initialProjects = requests.shift();
  assert.equal(initialProjects.url, '/api/projects');
  initialProjects.reply([]);
  await settle();
  const initialGraph = requests.shift();
  assert.equal(initialGraph.url, '/api/graph');
  initialGraph.reply({ error: 'No projects indexed yet. Run add.' });
  await settle();
  assert.equal(element('#empty b').textContent, 'Add your first repository');
  assert.equal(element('#empty-command').hidden, false);
  assert.equal(element('#empty-refresh').hidden, false);

  const refreshing = element('#empty-refresh').onclick();
  const updatedProjects = requests.shift();
  assert.equal(updatedProjects.url, '/api/projects');
  updatedProjects.reply([{ id: 'repo-1', root: '/private/repository', files: 1 }]);
  await settle();
  const updatedGraph = requests.shift();
  assert.equal(updatedGraph.url, '/api/graph?project=repo-1');
  updatedGraph.reply({ nodes: [], edges: [] });
  await refreshing;
  await settle();
  assert.equal(element('#project').value, 'repo-1');
  assert.equal(element('#empty-command').hidden, true);
  assert.equal(element('#empty b').textContent, 'Code indexed; graph has no knowledge yet');
  assert.equal(element('#empty-search').hidden, false);
  assert.equal(element('#empty-context-command').hidden, false);
  let searchOpened = false;
  element('#workspace-open').click = () => {
    searchOpened = true;
  };
  element('#empty-search').onclick();
  assert.equal(searchOpened, true);
});

test('graph failures show a recovery action without echoing server path details', async () => {
  const { element, requests } = setup();
  requests.shift().reply([{ id: 'repo-1', root: '/private/repository', files: 1 }]);
  await settle();
  const graph = requests.shift();
  assert.equal(graph.url, '/api/graph?project=repo-1');
  graph.reply({ error: 'Failed to open /private/repository/secrets.py' });
  await settle();
  assert.equal(element('#empty b').textContent, 'Graph unavailable');
  assert.equal(element('#empty-refresh').hidden, false);
  assert.doesNotMatch(element('#empty span').textContent, /private|secrets/);
});

test('refresh preserves a deliberately selected shared graph', async () => {
  const { element, requests, scopes } = setup();
  requests.shift().reply([{ id: 'repo-1', root: '/private/repository', files: 1 }]);
  await settle();
  requests.shift().reply({ nodes: [], edges: [] });
  await settle();
  scopes[0].onclick();
  const sharedGraph = requests.shift();
  assert.equal(sharedGraph.url, '/api/graph');
  const refreshing = element('#refresh').onclick();
  const projects = requests.shift();
  assert.equal(projects.url, '/api/projects');
  projects.reply([{ id: 'repo-1', root: '/private/repository', files: 1 }]);
  await settle();
  const refreshedGraph = requests.shift();
  assert.equal(refreshedGraph.url, '/api/graph');
  assert.equal(scopes[0]['aria-pressed'], 'true');
  assert.equal(scopes[1]['aria-pressed'], 'false');
  sharedGraph.reply({ nodes: [], edges: [] });
  refreshedGraph.reply({ nodes: [], edges: [] });
  await refreshing;
});
