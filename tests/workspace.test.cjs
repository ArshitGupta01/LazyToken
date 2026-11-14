const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const { test } = require('node:test');
const vm = require('node:vm');

class Element {
  constructor() {
    this.children = [];
    this.textContent = '';
    this.dataset = {};
    this.classList = { toggle() {} };
  }
  append(...children) {
    this.children.push(...children);
  }
  replaceChildren(...children) {
    this.children = children;
    this.textContent = '';
  }
  setAttribute() {}
  addEventListener(name, handler) {
    this[name] = handler;
  }
}

function setup() {
  const elements = new Map();
  const node = (selector) => {
    if (!elements.has(selector)) elements.set(selector, new Element());
    return elements.get(selector);
  };
  const navigation = ['search', 'proposals', 'dependencies', 'graph'].map((view) => {
    const button = new Element();
    button.dataset.workspaceView = view;
    return button;
  });
  node('#project').value = 'one';
  node('#project').selectedOptions = [{ textContent: 'Project one' }];
  node('#knowledge-workspace').hidden = true;
  const requests = [];
  const context = {
    URLSearchParams,
    document: {
      querySelector: node,
      querySelectorAll: (selector) => (selector === '[data-workspace-view]' ? navigation : []),
      createElement: () => new Element(),
      createTextNode: (textContent) => ({ textContent })
    },
    fetch: (url, options) =>
      new Promise((resolve) => {
        requests.push({
          url,
          options,
          reply: (data, ok = true) => resolve({ ok, json: async () => data })
        });
      })
  };
  vm.runInNewContext(readFileSync(join(__dirname, '../features-ui.js'), 'utf8'), context);
  requests.shift().reply({ runs: [] });
  return {
    node,
    requests,
    open: (view) => navigation.find((button) => button.dataset.workspaceView === view).onclick()
  };
}

const settle = () => new Promise((resolve) => setImmediate(resolve));
const text = (node) => [node.textContent, ...(node.children || []).map(text)].join(' ');

test('late responses cannot replace the newly selected workspace view', async () => {
  const { node, requests, open } = setup();
  open('dependencies');
  const old = requests.shift();
  open('proposals');
  const current = requests.shift();
  old.reply({ dependencies: [], note: 'Old dependencies' });
  await settle();
  assert.equal(text(node('#workspace-body')).trim(), 'Loading…');
  current.reply({ proposals: [] });
  await settle();
  assert.match(text(node('#workspace-body')), /No memory proposals/);
});

test('a later search wins even when the older request finishes last', async () => {
  const { node, requests, open } = setup();
  open('search');
  const form = node('#workspace-body').children[0];
  form.children[0].value = 'old';
  form.onsubmit({ preventDefault() {} });
  const old = requests.shift();
  form.children[0].value = 'new';
  form.onsubmit({ preventDefault() {} });
  requests.shift().reply({ results: [{ name: 'New result', type: 'file', path: 'new.py' }] });
  await settle();
  old.reply({ results: [{ name: 'Old result', type: 'file', path: 'old.py' }] });
  await settle();
  assert.match(text(node('#workspace-body')), /New result/);
  assert.doesNotMatch(text(node('#workspace-body')), /Old result/);
});

test('review keeps its project while the local session token is being fetched', async () => {
  const { node, requests, open } = setup();
  open('proposals');
  requests.shift().reply({
    proposals: [
      {
        id: 1,
        name: 'Lesson',
        kind: 'lesson',
        status: 'approved',
        freshness: 'current',
        paths: [],
        changed_paths: []
      }
    ]
  });
  await settle();
  const card = node('#workspace-body').children[0];
  const button = card.children.find((child) => child.textContent === 'Mark superseded');
  button.onclick();
  const token = requests.shift();
  node('#project').value = 'two';
  token.reply({ token: 'fixture' });
  await settle();
  const review = requests.shift();
  assert.equal(review.url, '/api/review');
  assert.equal(JSON.parse(review.options.body).project, 'one');
});
