// TokSmart Web Client & Server Connection Manager
(() => {
  'use strict';

  const DEFAULT_PORT = 8765;
  const POLL_INTERVAL = 3000;
  const STORAGE_KEY = 'toksmart_connected';
  const DISCONNECT_KEY = 'toksmart_disconnected';
  const LEGACY_STORAGE_KEYS = ['repomind_connected', 'lazytoken_connected'];
  const LEGACY_DISCONNECT_KEYS = ['repomind_disconnected', 'lazytoken_disconnected'];

  function getApiBase() {
    const isLocal =
      window.location.protocol === 'http:' &&
      (window.location.hostname === '127.0.0.1' || window.location.hostname === 'localhost');
    if (isLocal) return '';
    return 'http://127.0.0.1:' + DEFAULT_PORT;
  }
  window.API_BASE = getApiBase();

  const healthEndpoint = (window.API_BASE || '') + '/api/health';

  let isConnected = false;
  let isManuallyDisconnected = false;
  try {
    isManuallyDisconnected =
      localStorage.getItem(DISCONNECT_KEY) === 'true' ||
      LEGACY_DISCONNECT_KEYS.some((k) => localStorage.getItem(k) === 'true');
  } catch (e) {}

  let consecutiveFailures = 0;
  let connectionIntent = 0;
  let toastEl = null;

  function showToast(msg) {
    if (!toastEl) {
      toastEl = document.createElement('div');
      toastEl.className = 'server-toast';
      toastEl.setAttribute('role', 'status');
      document.body.appendChild(toastEl);
    }
    toastEl.textContent = msg;
    toastEl.hidden = false;
  }

  function hideToast() {
    if (toastEl) toastEl.hidden = true;
  }

  function setupCopyButtons() {
    const status = document.getElementById('copy-status');
    document.querySelectorAll('.copy-button').forEach((button) => {
      button.addEventListener('click', async () => {
        try {
          await navigator.clipboard.writeText(button.dataset.command);
          status.textContent = 'Command copied.';
        } catch {
          const selection = window.getSelection();
          if (selection) {
            const range = document.createRange();
            range.selectNodeContents(document.getElementById('launch-command'));
            selection.removeAllRanges();
            selection.addRange(range);
          }
          status.textContent = selection
            ? 'Command selected. Copy it manually.'
            : 'Select and copy the command manually.';
        }
      });
    });
  }

  // --- Local Health Check ---
  function pingEndpoint(url) {
    return new Promise((resolve, reject) => {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 2500);

      fetch(url, {
        method: 'GET',
        mode: 'cors',
        cache: 'no-store',
        signal: controller.signal
      })
        .then((res) => {
          if (!res.ok) throw new Error('Non-200 response');
          return res.json();
        })
        .then((data) => {
          clearTimeout(timeoutId);
          if (data.service === 'toksmart' || data.service === 'lazytoken') resolve();
          else reject(new Error('Not a TokSmart server'));
        })
        .catch((err) => {
          clearTimeout(timeoutId);
          reject(err);
        });
    });
  }

  function updateConnectCardServerReady(serverAlive) {
    const status = document.getElementById('connection-status');
    const button = document.getElementById('manual-connect-btn');
    if (status) {
      status.textContent = serverAlive
        ? 'Local server is running.'
        : 'Waiting for the local server…';
    }
    if (button) button.hidden = !serverAlive;
  }

  // --- Server Health Polling ---
  async function checkServer() {
    const intent = connectionIntent;
    if (isManuallyDisconnected) {
      try {
        await pingEndpoint(healthEndpoint);
        if (intent === connectionIntent) updateConnectCardServerReady(true);
      } catch {
        if (intent === connectionIntent) updateConnectCardServerReady(false);
      }
      return;
    }

    try {
      await pingEndpoint(healthEndpoint);
      if (intent !== connectionIntent) return;
      consecutiveFailures = 0;
      hideToast();
      handleServerFound();
    } catch {
      if (intent !== connectionIntent) return;
      consecutiveFailures++;
      if (!isConnected) updateConnectCardServerReady(false);
      if (isConnected && consecutiveFailures >= 3) {
        showToast('Local server disconnected. Checking connection...');
      }
    }
  }

  function handleServerFound() {
    isConnected = true;
    isManuallyDisconnected = false;
    try {
      localStorage.setItem(STORAGE_KEY, 'true');
      localStorage.removeItem(DISCONNECT_KEY);
      LEGACY_DISCONNECT_KEYS.forEach((k) => localStorage.removeItem(k));
      localStorage.setItem('toksmart_last_seen', Date.now().toString());
    } catch (e) {}

    window.API_BASE = getApiBase();
    const localAddress = window.location.host;
    const serverStatus = document.getElementById('header-server-status');
    if (serverStatus) serverStatus.title = 'Connected to local server at ' + localAddress;

    document.documentElement.classList.add('server-connected');
    document.body.classList.add('server-connected');

    if (window.startDashboard) {
      window.startDashboard();
    }
  }

  function handleDisconnect() {
    connectionIntent++;
    isManuallyDisconnected = true;
    isConnected = false;
    try {
      localStorage.setItem(DISCONNECT_KEY, 'true');
      localStorage.removeItem(STORAGE_KEY);
      LEGACY_STORAGE_KEYS.forEach((k) => localStorage.removeItem(k));
    } catch (e) {}

    document.documentElement.classList.remove('server-connected');
    document.body.classList.remove('server-connected');

    document.getElementById('connect-title')?.focus();
    updateConnectCardServerReady(false);
    checkServer();
  }

  function handleManualConnect() {
    connectionIntent++;
    isManuallyDisconnected = false;
    try {
      localStorage.removeItem(DISCONNECT_KEY);
      LEGACY_DISCONNECT_KEYS.forEach((k) => localStorage.removeItem(k));
      localStorage.setItem(STORAGE_KEY, 'true');
    } catch (e) {}
    checkServer();
  }

  function bootstrap() {
    setupCopyButtons();

    document.addEventListener('click', (e) => {
      const target = e.target;
      if (!target) return;
      if (target.id === 'disconnect-btn' || target.closest('#disconnect-btn')) {
        e.preventDefault();
        e.stopPropagation();
        handleDisconnect();
      } else if (target.id === 'manual-connect-btn' || target.closest('#manual-connect-btn')) {
        e.preventDefault();
        e.stopPropagation();
        handleManualConnect();
      }
    });

    if (isManuallyDisconnected) updateConnectCardServerReady(false);

    checkServer();
    setInterval(checkServer, POLL_INTERVAL);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bootstrap);
  } else {
    bootstrap();
  }
})();

// --- TokSmart Interactive Knowledge Graph & Visualizer Dashboard ---
(() => {
  let initialized = false;
  window.startDashboard = function () {
    if (initialized) return;
    initialized = true;

    runDashboardCode();
  };

  function runDashboardCode() {
    const $ = (selector) => document.querySelector(selector);
    const canvas = $('#graph'),
      ctx = canvas.getContext('2d'),
      host = $('#webgl-host');
    const root = document.documentElement;
    const palettes = {
      project: ['#385c29', '#c3f670'],
      framework: ['#536d2a', '#b4ce83'],
      library: ['#2d6b5c', '#69c8b4'],
      platform: ['#6b5b2d', '#c9b277'],
      pattern: ['#56507c', '#a9a4d1'],
      component: ['#4e684d', '#a0be92'],
      skill: ['#626046', '#b7bb95'],
      plugin: ['#356658', '#83c4ac'],
      decision: ['#357943', '#9ada91'],
      lesson: ['#6e6429', '#cfd980'],
      technology: ['#53674d', '#a5b49d']
    };
    const themeColors = {
      light: {
        activeEdge: '#355c1d',
        sharedEdge: '#698373',
        projectEdge: '#6c7d70',
        label: '#18221c',
        edgeLabel: '#355c1d',
        focus: '#325224'
      },
      dark: {
        activeEdge: '#c3f670',
        sharedEdge: '#839b8b',
        projectEdge: '#608371',
        label: '#f1f7ed',
        edgeLabel: '#deefc5',
        focus: '#ebfbd9'
      }
    };
    const activeTheme = () => (root?.dataset?.theme === 'dark' ? 'dark' : 'light');
    const color = (kind) =>
      (palettes[kind] || palettes.technology)[activeTheme() === 'dark' ? 1 : 0];
    const esc = (value = '') =>
      String(value).replace(
        /[&<>"']/g,
        (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]
      );
    let data = { nodes: [], edges: [] },
      projects = [],
      nodes = [],
      edges = [],
      kinds = new Set(),
      relations = new Set();
    let selected = null,
      hover = null,
      query = '',
      scope = '',
      healthFilter = 'all',
      zoom = 1,
      pan = { x: 0, y: 0 };
    let width = 0,
      height = 0,
      drag = null,
      frame = 0,
      view3d = false,
      gl = null,
      glLoading = null;
    let searchVisible = null,
      graphRequest = 0,
      jumpSignature = '',
      projectsLoaded = false;

    // Keep the selection intact while giving the graph the inspector's space.
    function setInspectorMinimized(minimized, moveFocus = false) {
      document.querySelector('.app-shell').classList.toggle('inspector-minimized', minimized);
      $('#inspector').hidden = minimized;
      $('#inspector-restore').hidden = !minimized;
      $('#inspector-restore').setAttribute('aria-expanded', String(!minimized));
      if (moveFocus) (minimized ? $('#inspector-restore') : $('#inspector-minimize')).focus();
    }
    $('#inspector-minimize').onclick = () => setInspectorMinimized(true, true);
    $('#inspector-restore').onclick = () => setInspectorMinimized(false, true);
    root?.addEventListener('toksmart-themechange', () => {
      $('#filters')
        .querySelectorAll('input')
        .forEach((input) => {
          input.parentElement.style.setProperty('--type-color', color(input.value));
        });
      draw();
    });

    async function loadProjects() {
      try {
        const response = await fetch((window.API_BASE || '') + '/api/projects');
        if (!response.ok) throw Error('Projects unavailable');
        projects = await response.json();
        projectsLoaded = true;
        $('#project').innerHTML =
          '<option value="">Choose a project…</option>' +
          projects
            .map(
              (p) =>
                `<option value="${esc(p.id)}">${esc(p.root.split(/[\\/]/).filter(Boolean).pop() || p.root)} · ${p.files} ${p.files === 1 ? 'file' : 'files'}</option>`
            )
            .join('');
      } catch {
        projects = [];
        projectsLoaded = false;
      }
    }
    function showEmptyState(noProjects, unavailable = false, indexedEmpty = false) {
      $('#empty').hidden = false;
      $('#empty b').textContent = noProjects
        ? 'Add your first repository'
        : unavailable
          ? 'Graph unavailable'
          : indexedEmpty
            ? 'Code indexed; graph has no knowledge yet'
            : 'No matching knowledge yet';
      $('#empty span').textContent = noProjects
        ? 'Keep the server running. In another terminal, run this command with your repository’s absolute folder path. Then refresh to search its code.'
        : unavailable
          ? 'Check that TokSmart is running, then refresh.'
          : indexedEmpty
            ? 'Your files are indexed. Search code in the workspace, or run a bounded task brief. Graph nodes appear when knowledge is recorded.'
            : projects.length
              ? 'Select a repository or try another search and scope.'
              : 'Refresh to check for indexed repositories.';
      $('#empty-command').hidden = !noProjects;
      $('#empty-refresh').hidden = !noProjects && !unavailable;
      $('#empty-search').hidden = !indexedEmpty;
      $('#empty-context-command').hidden = !indexedEmpty;
    }
    async function refreshGraph() {
      const hadProjects = projects.length > 0;
      await loadProjects();
      const nextScope =
        (!scope && !hadProjects) ||
        (scope && scope !== '@workspace' && !projects.some((p) => p.id === scope))
          ? projects.length > 1
            ? '@workspace'
            : projects[0]?.id || ''
          : scope;
      $('#project').value = nextScope === '@workspace' ? '' : nextScope;
      await loadGraph(nextScope);
    }
    async function loadGraph(project = '', background = false) {
      const requestId = ++graphRequest;
      scope = project;
      if (!background) {
        document.querySelectorAll('.scope').forEach((button) => {
          const active = button.dataset.project === scope;
          button.classList.toggle('active', active);
          button.setAttribute('aria-pressed', String(active));
        });
        $('#loading').hidden = false;
        $('#empty').hidden = true;
      }
      try {
        const response = await fetch(
          (window.API_BASE || '') +
            '/api/graph' +
            (project === '@workspace'
              ? '?workspace=1'
              : project
                ? '?project=' + encodeURIComponent(project)
                : '')
        );
        const next = await response.json();
        if (requestId !== graphRequest) return;
        if (!response.ok || next.error) throw Error(next.error || 'Could not read graph');
        if (background && JSON.stringify(next) === JSON.stringify(data)) return;
        data = next;
        $('#scope-label').textContent =
          project === '@workspace'
            ? 'All indexed projects'
            : project
              ? `Project · ${
                  projects
                    .find((p) => p.id === project)
                    ?.root.split(/[\\/]/)
                    .filter(Boolean)
                    .pop() || 'selected'
                }`
              : 'Shared knowledge';
        buildFilters();
        layout();
        if (selected) {
          selected = nodes.find((n) => n.id === selected.id) || null;
          inspector(selected);
        }
        hover = null;
        draw();
      } catch (error) {
        if (requestId !== graphRequest || background) return;
        data = { nodes: [], edges: [] };
        nodes = [];
        edges = [];
        showEmptyState(
          projectsLoaded &&
            projects.length === 0 &&
            error.message.startsWith('No projects indexed yet.'),
          true
        );
        updateCounts([], []);
      } finally {
        if (requestId === graphRequest) $('#loading').hidden = true;
      }
    }
    function buildFilters() {
      const previous = new Map(
        [...$('#filters').querySelectorAll('input')].map((i) => [i.value, i.checked])
      );
      const counts = {};
      data.nodes.forEach((n) => (counts[n.kind] = (counts[n.kind] || 0) + 1));
      $('#filters').innerHTML = Object.entries(counts)
        .sort((a, b) => a[0].localeCompare(b[0]))
        .map(
          ([kind, count]) =>
            `<label class="filter-row" style="--type-color:${color(kind)}"><input type="checkbox" value="${esc(kind)}" ${!previous.has(kind) || previous.get(kind) ? 'checked' : ''}><span class="type-dot" aria-hidden="true"></span><span>${esc(kind[0].toUpperCase() + kind.slice(1))}</span><span class="count">${count}</span></label>`
        )
        .join('');
      const updateKinds = () => {
        kinds = new Set([...$('#filters').querySelectorAll('input:checked')].map((i) => i.value));
        draw();
      };
      $('#filters').onchange = updateKinds;
      updateKinds();
      relations = new Set(data.edges.map((edge) => edge.relation));
      draw();
    }
    function layout() {
      const rect = canvas.parentElement.getBoundingClientRect(),
        dpr = Math.min(devicePixelRatio || 1, 2);
      width = rect.width;
      height = rect.height;
      if (!width || !height) return;
      canvas.width = width * dpr;
      canvas.height = height * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const list = data.nodes,
        n = list.length,
        cx = width / 2,
        cy = height / 2,
        groups = {};
      list.forEach((a) => (groups[a.kind] ??= []).push(a));
      const groupKeys = Object.keys(groups).sort(),
        positions = new Map();
      groupKeys.forEach((kind, gi) => {
        const members = groups[kind],
          base = groupKeys.length === 1 ? 0 : (gi * 2 * Math.PI) / groupKeys.length - 0.6,
          ring = Math.min(width, height) * (groupKeys.length < 3 ? 0.26 : 0.32);
        members.forEach((a, i) => {
          const angle = base + i * 2.39996,
            r = ring * (0.72 + 0.28 * Math.sqrt((i + 1) / members.length));
          positions.set(a.id, { x: cx + Math.cos(angle) * r, y: cy + Math.sin(angle) * r });
        });
      });
      nodes = list.map((a) => {
        const pos = positions.get(a.id) || { x: cx, y: cy };
        return {
          ...a,
          x: pos.x,
          y: pos.y,
          vx: 0,
          vy: 0,
          r: n > 100 ? 6 : n > 40 ? 8 : n > 20 ? 12 : 19,
          z: ((Math.sin(Number(a.id) * 12.9898) * 43758.5453) % 1) * 210
        };
      });
      const byId = new Map(nodes.map((n) => [n.id, n])),
        byName = new Map(nodes.map((n) => [n.name, n]));
      edges = data.edges
        .map((e) => ({
          ...e,
          a: byId.get(e.source_id) || byName.get(e.source),
          b: byId.get(e.target_id) || byName.get(e.target)
        }))
        .filter((e) => e.a && e.b);
      const iterations = n > 250 ? 20 : n > 100 ? 40 : 100;
      for (let iter = 0; iter < iterations; iter++) {
        for (const e of edges) {
          const dx = e.b.x - e.a.x,
            dy = e.b.y - e.a.y,
            d = Math.hypot(dx, dy) || 1,
            target = 150 + (1 - (+e.weight || 0.5)) * 35,
            f = ((d - target) / d) * 0.008;
          e.a.vx += dx * f;
          e.a.vy += dy * f;
          e.b.vx -= dx * f;
          e.b.vy -= dy * f;
        }
        for (let i = 0; i < n; i++)
          for (let j = i + 1; j < n; j++) {
            const a = nodes[i],
              b = nodes[j],
              dx = b.x - a.x,
              dy = b.y - a.y,
              d2 = dx * dx + dy * dy;
            if (d2 < 19600 && d2 > 0) {
              const f = 85 / d2;
              a.vx -= dx * f;
              a.vy -= dy * f;
              b.vx += dx * f;
              b.vy += dy * f;
            }
          }
        for (const a of nodes) {
          const g = positions.get(a.id);
          a.vx += (g.x - a.x) * 0.004;
          a.vy += (g.y - a.y) * 0.004;
          a.x += a.vx;
          a.y += a.vy;
          a.vx *= 0.8;
          a.vy *= 0.8;
        }
      }
    }
    function baseVisible(n) {
      const verified = n.verification_state === 'verified' && n.freshness === 'current';
      const health =
        healthFilter === 'all' ||
        (healthFilter === 'verified' && verified) ||
        (healthFilter === 'stale' && n.freshness === 'stale') ||
        (healthFilter === 'unverified' && !verified && n.freshness !== 'stale');
      return health && kinds.has(n.kind);
    }
    function matchesQuery(n) {
      return `${n.name} ${n.kind} ${n.summary} ${n.tags}`.toLowerCase().includes(query);
    }
    function visible(n) {
      return baseVisible(n) && (!query || !!searchVisible?.has(n));
    }
    function filtered() {
      if (query) {
        const matches = new Set(nodes.filter((n) => baseVisible(n) && matchesQuery(n)));
        searchVisible = new Set(matches);
        for (const edge of edges) {
          if (!relations.has(edge.relation)) continue;
          if (matches.has(edge.a) && baseVisible(edge.b)) searchVisible.add(edge.b);
          if (matches.has(edge.b) && baseVisible(edge.a)) searchVisible.add(edge.a);
        }
      } else searchVisible = null;
      const shown = nodes.filter(visible),
        ids = new Set(shown);
      return {
        shown,
        links: edges.filter((e) => ids.has(e.a) && ids.has(e.b) && relations.has(e.relation))
      };
    }
    function updateCounts(shown, links) {
      const evidence = links.filter((e) => e.evidence).length;
      for (const [id, v] of [
        ['node-count', shown.length],
        ['edge-count', links.length],
        ['evidence-count', evidence]
      ])
        $('#' + id).textContent = v;
    }
    function draw() {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const { shown, links } = filtered(),
          focus = hover || selected,
          visuals = themeColors[activeTheme()];
        updateCounts(shown, links);
        const signature = shown.map((n) => n.id + ':' + n.name).join('|');
        if (signature !== jumpSignature) {
          jumpSignature = signature;
          $('#node-jump').innerHTML =
            '<option value="">Choose a node…</option>' +
            shown.map((n) => `<option value="${n.id}">${esc(n.name)}</option>`).join('');
        }
        $('#node-jump').value = selected && shown.includes(selected) ? String(selected.id) : '';
        if (!shown.length) {
          showEmptyState(
            projectsLoaded && projects.length === 0 && data.nodes.length === 0,
            false,
            projects.length > 0 && scope && data.nodes.length === 0 && !query
          );
        } else {
          $('#empty').hidden = true;
        }
        const note = $('#edge-note'),
          truncated = data.nodes_truncated || data.edges_truncated;
        note.hidden = !shown.length || (!truncated && links.length > 0);
        note.textContent = truncated
          ? 'Large graph: showing up to 500 assets and 3,000 relationships.'
          : scope
            ? 'No relationships in the current view.'
            : projects.length
              ? 'No global relationships. Select a project to see its connections.'
              : 'No relationships recorded yet.';
        if (view3d && gl) {
          gl.setState({
            nodes: shown,
            edges: links,
            selected,
            hovered: hover,
            width,
            height,
            visuals
          });
          return;
        }
        ctx.clearRect(0, 0, width, height);
        ctx.save();
        ctx.translate(width / 2 + pan.x, height / 2 + pan.y);
        ctx.scale(zoom, zoom);
        ctx.translate(-width / 2, -height / 2);
        for (const edge of links) {
          const active = focus && (edge.a === focus || edge.b === focus);
          ctx.beginPath();
          ctx.moveTo(edge.a.x, edge.a.y);
          ctx.lineTo(edge.b.x, edge.b.y);
          ctx.setLineDash(edge.scope === '*' ? [] : [4, 4]);
          ctx.strokeStyle = active
            ? visuals.activeEdge
            : edge.scope === '*'
              ? visuals.sharedEdge
              : visuals.projectEdge;
          ctx.lineWidth = active ? 2 : 0.9 + Math.max(0, Math.min(1, Number(edge.weight) || 0));
          ctx.stroke();
          ctx.setLineDash([]);
          if (active) {
            const x = (edge.a.x + edge.b.x) / 2,
              y = (edge.a.y + edge.b.y) / 2;
            ctx.fillStyle = visuals.edgeLabel;
            ctx.font = '11px Consolas, monospace';
            ctx.textAlign = 'center';
            ctx.fillText(edge.relation.replaceAll('_', ' '), x, y - 7);
          }
        }
        const linked = new Set(
          focus
            ? links.filter((e) => e.a === focus || e.b === focus).flatMap((e) => [e.a, e.b])
            : []
        );
        for (const n of shown) {
          const isSelected = selected === n,
            near = linked.has(n),
            dim = focus && focus !== n && !near;
          ctx.globalAlpha = dim ? 0.46 : 1;
          const c = color(n.kind);
          ctx.beginPath();
          ctx.arc(n.x, n.y, n.r * 0.68, 0, Math.PI * 2);
          ctx.fillStyle = c;
          ctx.fill();
          if (isSelected || n === hover) {
            ctx.beginPath();
            ctx.arc(n.x, n.y, n.r * 0.68 + 4, 0, Math.PI * 2);
            ctx.lineWidth = 1.3;
            ctx.strokeStyle = visuals.focus;
            ctx.stroke();
          }
          ctx.font = `${isSelected ? '600 ' : ''}12px Segoe UI, sans-serif`;
          ctx.textAlign = 'center';
          ctx.fillStyle = visuals.label;
          if (shown.length <= 60 || isSelected || near || n === hover)
            ctx.fillText(n.name, n.x, n.y + n.r + 13);
          ctx.globalAlpha = 1;
        }
        ctx.restore();
      });
    }
    function screenPoint(e) {
      const rect = canvas.getBoundingClientRect();
      return { x: e.clientX - rect.left, y: e.clientY - rect.top };
    }
    function world(p) {
      return {
        x: (p.x - width / 2 - pan.x) / zoom + width / 2,
        y: (p.y - height / 2 - pan.y) / zoom + height / 2
      };
    }
    function hit(p) {
      const point = world(p);
      return [...nodes]
        .reverse()
        .find((n) => visible(n) && Math.hypot(n.x - point.x, n.y - point.y) < n.r + 8);
    }
    function inspector(node) {
      selected = node;
      const detail = $('#detail'),
        placeholder = $('.inspector-empty');
      placeholder.hidden = !!node;
      detail.hidden = !node;
      if (!node) {
        detail.innerHTML = '';
        const jump = $('#node-jump');
        if (jump) jump.value = '';
        draw();
        return;
      }
      const links = edges
          .filter((e) => e.a === node || e.b === node)
          .sort((a, b) => b.weight - a.weight),
        tags = (node.tags || '')
          .split(',')
          .map((x) => x.trim())
          .filter(Boolean);
      detail.innerHTML = `<div class="detail-top"><span class="kind-pill">${esc(node.kind)}</span><span class="detail-scope">${node.scope === 'global' ? 'Shared' : 'Repository'}</span></div><h2 class="detail-name">${esc(node.name)}</h2><p class="detail-summary">${esc(node.summary || 'No summary has been added yet.')}</p>${tags.length ? `<div class="tag-list">${tags.map((t) => `<span class="tag"># ${esc(t)}</span>`).join('')}</div>` : ''}${node.freshness ? `<div class="memory-health"><span>Evidence status</span><strong>${esc(node.freshness)} · ${esc(node.verification_state || 'unverified')}</strong></div>` : ''}<div class="detail-section"><h3>Relationships <span>${links.length}</span></h3>${
        links.length
          ? links
              .map((edge) => {
                const other = edge.a === node ? edge.b : edge.a;
                return `<div class="connection"><div class="connection-line"><b>${esc(other.name)}</b><span>${esc(edge.relation.replaceAll('_', ' '))}</span></div><div class="connection-meta"><span>${
                  edge.scope === '*'
                    ? 'GLOBAL'
                    : esc(
                        projects
                          .find((p) => p.id === edge.scope)
                          ?.root.split(/[\\/]/)
                          .filter(Boolean)
                          .pop() || edge.scope
                      )
                }</span><span>WEIGHT <strong>${Number(edge.weight).toFixed(2)}</strong></span></div>${edge.evidence ? `<div class="evidence">${esc(edge.evidence)}</div>` : ''}</div>`;
              })
              .join('')
          : '<p class="detail-summary">No relationships in this scope.</p>'
      }</div>${node.source ? `<span class="source">Source &nbsp; ${esc(node.source)}</span>` : ''}`;
      draw();
    }
    canvas.addEventListener('keydown', (event) => {
      if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Enter'].includes(event.key)) return;
      const available = nodes.filter(visible);
      if (!available.length) return;
      event.preventDefault();
      let index = available.findIndex((node) => node.id === selected?.id);
      if (event.key !== 'Enter') {
        const step = ['ArrowLeft', 'ArrowUp'].includes(event.key) ? -1 : 1;
        index =
          index < 0
            ? step > 0
              ? 0
              : available.length - 1
            : (index + step + available.length) % available.length;
        setInspectorMinimized(false);
        inspector(available[index]);
      } else if (selected) {
        pan.x = (width / 2 - selected.x) * zoom;
        pan.y = (height / 2 - selected.y) * zoom;
        draw();
      } else {
        setInspectorMinimized(false);
        inspector(available[0]);
      }
    });
    canvas.addEventListener('pointerdown', (event) => {
      canvas.setPointerCapture(event.pointerId);
      const p = screenPoint(event),
        node = hit(p);
      const isSameNode = !!(node && selected && String(selected.id) === String(node.id));
      drag = { x: p.x, y: p.y, lastX: p.x, lastY: p.y, node, moved: false, toggleOff: isSameNode };
      canvas.classList.add('dragging');
      if (node && !isSameNode) {
        setInspectorMinimized(false);
        inspector(node);
      }
    });
    canvas.addEventListener('pointermove', (event) => {
      const p = screenPoint(event);
      if (drag) {
        const dx = p.x - drag.lastX,
          dy = p.y - drag.lastY;
        if (Math.abs(p.x - drag.x) + Math.abs(p.y - drag.y) > 3) drag.moved = true;
        if (drag.node && drag.moved) {
          const w = world(p);
          drag.node.x = w.x;
          drag.node.y = w.y;
          draw();
        } else if (!drag.node) {
          pan.x += dx;
          pan.y += dy;
          draw();
        }
        drag.lastX = p.x;
        drag.lastY = p.y;
        return;
      }
      const node = hit(p);
      canvas.style.cursor = node ? 'pointer' : 'grab';
      if (node !== hover) {
        hover = node;
        draw();
        const tip = $('#tooltip');
        tip.hidden = !node;
        if (node) {
          tip.textContent = `${node.name} · ${node.kind}`;
          tip.style.left = `${Math.min(p.x + 13, width - 190)}px`;
          tip.style.top = `${Math.min(p.y + 13, height - 40)}px`;
        }
      }
    });
    canvas.addEventListener('pointerleave', () => {
      if (!drag) {
        hover = null;
        $('#tooltip').hidden = true;
        draw();
      }
    });
    for (const name of ['pointerup', 'pointercancel'])
      canvas.addEventListener(name, () => {
        if (drag && drag.toggleOff && !drag.moved) {
          // Clicking on the currently open node closes the node inspector
          inspector(null);
          setInspectorMinimized(true);
        }
        drag = null;
        canvas.classList.remove('dragging');
      });
    canvas.addEventListener(
      'wheel',
      (event) => {
        event.preventDefault();
        zoom = Math.min(2.8, Math.max(0.4, zoom * (event.deltaY < 0 ? 1.1 : 0.91)));
        draw();
      },
      { passive: false }
    );
    async function setView(three) {
      view3d = three;
      $('#view-2d').classList.toggle('active', !three);
      $('#view-3d').classList.toggle('active', three);
      $('#view-2d').setAttribute('aria-pressed', String(!three));
      $('#view-3d').setAttribute('aria-pressed', String(three));
      $('#canvas-hint').textContent = three
        ? 'Drag to orbit · Right-drag to pan · Scroll to zoom'
        : 'Drag to move · Scroll to zoom';
      if (!three) {
        canvas.hidden = false;
        host.hidden = true;
        if (gl) gl.setActive(false);
        draw();
        return;
      }
      try {
        let module;
        if (!gl) {
          glLoading ??= import('./graph3d.js');
          module = await glLoading;
        }
        if (!view3d) return;
        if (!gl) {
          host.hidden = false;
          gl = module.createGraph3D(host, {
            onUnavailable: () => {
              setView(false);
              $('#canvas-hint').textContent = '3D graphics became unavailable · showing 2D';
              if (gl) {
                gl.dispose();
                gl = null;
              }
            },
            onSelect: (node) => {
              if (!node) {
                inspector(null);
                setInspectorMinimized(true);
                return;
              }
              const found = nodes.find((n) => String(n.id) === String(node.id)) || null;
              if (selected && found && String(selected.id) === String(found.id)) {
                inspector(null);
                setInspectorMinimized(true);
              } else if (found) {
                setInspectorMinimized(false);
                inspector(found);
              }
            },
            onHover: (node) => {
              hover = node ? nodes.find((n) => n.id === node.id) || null : null;
              draw();
            },
            color
          });
        }
        canvas.hidden = true;
        host.hidden = false;
        gl.setActive(true);
        draw();
        if (selected)
          requestAnimationFrame(() => {
            if (view3d && gl && selected) gl.focus(selected);
          });
      } catch (error) {
        console.error('3D view unavailable', error);
        view3d = false;
        canvas.hidden = false;
        host.hidden = true;
        glLoading = null;
        $('#view-2d').classList.add('active');
        $('#view-3d').classList.remove('active');
        $('#view-2d').setAttribute('aria-pressed', 'true');
        $('#view-3d').setAttribute('aria-pressed', 'false');
        $('#canvas-hint').textContent = '3D unavailable on this device · showing 2D';
        draw();
      }
    }
    $('#node-jump').onchange = (event) => {
      const node = nodes.find((n) => String(n.id) === event.target.value);
      if (!node) return;
      inspector(node);
      setInspectorMinimized(false);
      if (view3d && gl) gl.focus(node);
      else {
        pan.x = (width / 2 - node.x) * zoom;
        pan.y = (height / 2 - node.y) * zoom;
        draw();
      }
    };
    $('#view-2d').onclick = () => setView(false);
    $('#view-3d').onclick = () => setView(true);
    $('#health-filter').onchange = (e) => {
      healthFilter = e.target.value;
      draw();
    };
    $('#search').oninput = (e) => {
      query = e.target.value.trim().toLowerCase();
      draw();
    };
    $('#search').onkeydown = (e) => {
      if (e.key === 'Enter' && query) {
        const match = nodes.find((n) => baseVisible(n) && matchesQuery(n));
        if (match) {
          setInspectorMinimized(false);
          inspector(match);
          if (view3d && gl) gl.focus(match);
          else {
            pan.x = (width / 2 - match.x) * zoom;
            pan.y = (height / 2 - match.y) * zoom;
            draw();
          }
        }
      }
    };
    $('#project').onchange = (e) => {
      loadGraph(e.target.value);
    };
    document.querySelectorAll('.scope').forEach(
      (button) =>
        (button.onclick = () => {
          $('#project').value = '';
          loadGraph(button.dataset.project || '');
        })
    );
    $('#fit').onclick = () => {
      if (view3d && gl) {
        gl.fit();
        return;
      }
      const { shown } = filtered();
      if (!shown.length) {
        zoom = 1;
        pan = { x: 0, y: 0 };
        draw();
        return;
      }
      ctx.save();
      ctx.font = '600 12px Segoe UI, sans-serif';
      const bounds = shown.map((node) => ({
        node,
        halfWidth: Math.max(node.r + 4, ctx.measureText(node.name).width / 2)
      }));
      ctx.restore();
      const left = Math.min(...bounds.map(({ node, halfWidth }) => node.x - halfWidth));
      const right = Math.max(...bounds.map(({ node, halfWidth }) => node.x + halfWidth));
      const top = Math.min(...shown.map((node) => node.y - node.r - 4));
      const bottom = Math.max(...shown.map((node) => node.y + node.r + 16));
      const padding = 24;
      zoom = Math.max(
        0.1,
        Math.min(1, (width - 2 * padding) / (right - left), (height - 2 * padding) / (bottom - top))
      );
      pan = {
        x: ((width - left - right) / 2) * zoom,
        y: ((height - top - bottom) / 2) * zoom
      };
      draw();
    };
    $('#zoom-in').onclick = () => {
      if (view3d && gl) gl.zoom(0.82);
      else {
        zoom = Math.min(2.8, zoom * 1.18);
        draw();
      }
    };
    $('#zoom-out').onclick = () => {
      if (view3d && gl) gl.zoom(1.22);
      else {
        zoom = Math.max(0.4, zoom / 1.18);
        draw();
      }
    };
    $('#refresh').onclick = refreshGraph;
    $('#empty-refresh').onclick = refreshGraph;
    $('#empty-search').onclick = () => $('#workspace-open').click();
    $('#clear-filters').onclick = () => {
      $('#filters')
        .querySelectorAll('input')
        .forEach((i) => (i.checked = true));
      kinds = new Set(data.nodes.map((n) => n.kind));
      relations = new Set(data.edges.map((e) => e.relation));
      $('#search').value = '';
      query = '';
      healthFilter = 'all';
      $('#health-filter').value = 'all';
      draw();
    };
    document.addEventListener('keydown', (event) => {
      if (
        event.key === '/' &&
        !['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement.tagName)
      ) {
        event.preventDefault();
        $('#search').focus();
      }
      if (event.key === 'Escape') {
        inspector(null);
        $('#search').blur();
      }
    });
    new ResizeObserver(() => {
      const id = selected?.id;
      layout();
      selected = nodes.find((n) => n.id === id) || null;
      if (selected) inspector(selected);
      if (gl) gl.resize();
      draw();
    }).observe(canvas.parentElement);
    setInterval(() => {
      if (!document.hidden && !drag) loadGraph(scope, true);
    }, 10000);
    refreshGraph();
  }
})();
