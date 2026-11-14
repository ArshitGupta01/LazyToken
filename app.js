(() => {
  const $ = (selector) => document.querySelector(selector);
  const canvas = $('#graph'),
    ctx = canvas.getContext('2d'),
    host = $('#webgl-host');
  const palette = {
    project: '#22e6f0',
    framework: '#20d9ff',
    library: '#39ead4',
    platform: '#4f8fff',
    pattern: '#b36cff',
    component: '#e59fff',
    skill: '#a88dff',
    plugin: '#55d9d0',
    decision: '#d37cff',
    lesson: '#e58dff',
    technology: '#38c9ff'
  };
  const color = (kind) => palette[kind] || '#83a7e7';
  const esc = (value = '') =>
    String(value).replace(
      /[&<>"']/g,
      (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]
    );
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
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
    jumpSignature = '';

  // Keep the selection intact while giving the graph the inspector's space.
  function setInspectorMinimized(minimized) {
    document.querySelector('.app-shell').classList.toggle('inspector-minimized', minimized);
    $('#inspector').hidden = minimized;
    $('#inspector-restore').hidden = !minimized;
    $('#inspector-restore').setAttribute('aria-expanded', String(!minimized));
    (minimized ? $('#inspector-restore') : $('#inspector-minimize')).focus();
  }
  $('#inspector-minimize').onclick = () => setInspectorMinimized(true);
  $('#inspector-restore').onclick = () => setInspectorMinimized(false);

  async function loadProjects() {
    try {
      const response = await fetch('/api/projects');
      if (!response.ok) throw Error('Projects unavailable');
      projects = await response.json();
      $('#project').innerHTML =
        '<option value="">Choose a project…</option>' +
        projects
          .map(
            (p) =>
              `<option value="${esc(p.id)}">${esc(p.root.split(/[\\/]/).filter(Boolean).pop() || p.root)} · ${p.files} files</option>`
          )
          .join('');
    } catch {
      projects = [];
    }
  }
  async function loadGraph(project = '', background = false) {
    const requestId = ++graphRequest;
    scope = project;
    if (!background) {
      $('#loading').hidden = false;
      $('#empty').hidden = true;
    }
    try {
      const response = await fetch(
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
      $('#empty').hidden = false;
      $('#empty b').textContent = 'Graph unavailable';
      $('#empty span').textContent = error.message;
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
      ['evidence-count', evidence],
      ['analytics-nodes', shown.length],
      ['analytics-edges', links.length],
      ['analytics-evidence', evidence]
    ])
      $('#' + id).textContent = v;
  }
  function draw() {
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(() => {
      const { shown, links } = filtered(),
        focus = hover || selected;
      updateCounts(shown, links);
      const signature = shown.map((n) => n.id + ':' + n.name).join('|');
      if (signature !== jumpSignature) {
        jumpSignature = signature;
        $('#node-jump').innerHTML =
          '<option value="">Choose a node…</option>' +
          shown.map((n) => `<option value="${n.id}">${esc(n.name)}</option>`).join('');
      }
      $('#node-jump').value = selected && shown.includes(selected) ? String(selected.id) : '';
      $('#empty').hidden = shown.length > 0;
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
        gl.setState({ nodes: shown, edges: links, selected, hovered: hover, width, height });
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
        ctx.setLineDash(edge.scope === '*' ? [] : [5, 5]);
        ctx.lineDashOffset = reduced.matches ? 0 : -(performance.now() / 100) % 10;
        ctx.strokeStyle = active ? '#aff6ffff' : '#39bde9a8';
        ctx.lineWidth = active ? 2.4 : 1.2 + Math.max(0, Math.min(1, Number(edge.weight) || 0));
        if (shown.length < 100) {
          ctx.shadowColor = '#14cfff';
          ctx.shadowBlur = active ? 14 : 6;
        }
        ctx.stroke();
        ctx.shadowBlur = 0;
        ctx.setLineDash([]);
        if (active) {
          const x = (edge.a.x + edge.b.x) / 2,
            y = (edge.a.y + edge.b.y) / 2;
          ctx.fillStyle = '#b8d5ed';
          ctx.font = '10px Segoe UI, sans-serif';
          ctx.textAlign = 'center';
          ctx.fillText(edge.relation.replaceAll('_', ' '), x, y - 7);
        }
      }
      const linked = new Set(
        focus ? links.filter((e) => e.a === focus || e.b === focus).flatMap((e) => [e.a, e.b]) : []
      );
      for (const n of shown) {
        const isSelected = selected === n,
          near = linked.has(n),
          dim = focus && focus !== n && !near;
        ctx.globalAlpha = dim ? 0.28 : 1;
        const c = color(n.kind);
        ctx.beginPath();
        ctx.arc(n.x, n.y, n.r + (isSelected ? 2 : 0), 0, Math.PI * 2);
        ctx.shadowColor = c;
        ctx.shadowBlur = shown.length < 100 ? (isSelected ? 28 : 18) : 0;
        ctx.fillStyle = '#09192e';
        ctx.fill();
        ctx.lineWidth = 1.8;
        ctx.strokeStyle = c;
        ctx.stroke();
        ctx.shadowBlur = 0;
        ctx.beginPath();
        ctx.arc(n.x, n.y, Math.max(2, n.r * 0.37), 0, Math.PI * 2);
        ctx.fillStyle = c;
        ctx.fill();
        ctx.font = `${isSelected ? '600 ' : ''}11px Segoe UI, sans-serif`;
        ctx.textAlign = 'center';
        ctx.fillStyle = '#e2edf9';
        if (shown.length <= 60 || isSelected || near || n === hover)
          ctx.fillText(n.name, n.x, n.y + n.r + 17);
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
    detail.innerHTML = `<div class="detail-top"><span class="kind-pill">${esc(node.kind)}</span><span class="detail-scope">${node.scope === 'global' ? 'SHARED' : 'PROJECT SCOPED'}</span></div><h2 class="detail-name">${esc(node.name)}</h2><p class="detail-summary">${esc(node.summary || 'No summary has been added yet.')}</p>${tags.length ? `<div class="tag-list">${tags.map((t) => `<span class="tag"># ${esc(t)}</span>`).join('')}</div>` : ''}${node.freshness ? `<div class="memory-health"><span>Evidence status</span><strong>${esc(node.freshness)} · ${esc(node.verification_state || 'unverified')}</strong></div>` : ''}<div class="detail-section"><h3>LINKED KNOWLEDGE <span>${links.length}</span></h3>${
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
    }</div>${node.source ? `<span class="source">SOURCE &nbsp; ${esc(node.source)}</span>` : ''}`;
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
      inspector(available[index]);
    } else if (selected) {
      pan.x = (width / 2 - selected.x) * zoom;
      pan.y = (height / 2 - selected.y) * zoom;
      draw();
    } else inspector(available[0]);
  });
  canvas.addEventListener('pointerdown', (event) => {
    canvas.setPointerCapture(event.pointerId);
    const p = screenPoint(event),
      node = hit(p);
    drag = { x: p.x, y: p.y, lastX: p.x, lastY: p.y, node, moved: false };
    canvas.classList.add('dragging');
    if (node) inspector(node);
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
    $('#graph-mode-label').textContent = three ? '3D KNOWLEDGE UNIVERSE' : '2D RELATIONSHIP MAP';
    $('#canvas-hint').textContent = three
      ? 'DRAG TO ORBIT · RIGHT DRAG TO PAN · SCROLL TO ZOOM'
      : 'DRAG NODES OR CANVAS · SCROLL TO ZOOM';
    if (!three) {
      canvas.hidden = false;
      host.hidden = true;
      if (gl) gl.setActive(false);
      draw();
      return;
    }
    try {
      if (!gl) {
        glLoading ??= import('./graph3d.js');
        const module = await glLoading;
        if (!view3d) return;
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
          onSelect: (node) => inspector(nodes.find((n) => n.id === node.id) || null),
          onHover: (node) => {
            hover = node ? nodes.find((n) => n.id === node.id) || null : null;
            draw();
          },
          color
        });
      }
      if (!view3d) return;
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
      $('#graph-mode-label').textContent = '2D RELATIONSHIP MAP';
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
    document
      .querySelectorAll('.scope')
      .forEach((b) => b.classList.toggle('active', !e.target.value && b.dataset.project === ''));
    loadGraph(e.target.value);
  };
  document.querySelectorAll('.scope').forEach(
    (button) =>
      (button.onclick = () => {
        $('#project').value = '';
        document
          .querySelectorAll('.scope')
          .forEach((b) => b.classList.toggle('active', b === button));
        loadGraph(button.dataset.project || '');
      })
  );
  $('#fit').onclick = () => {
    if (view3d && gl) gl.reset();
    else {
      zoom = 1;
      pan = { x: 0, y: 0 };
      draw();
    }
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
  $('#refresh').onclick = () => loadGraph(scope);
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
  setInterval(() => {
    if (!view3d && !document.hidden && !reduced.matches && edges.length <= 150) draw();
  }, 100);
  loadProjects().then(() => {
    const initial =
      projects.length > 1 ? '@workspace' : projects.length === 1 ? projects[0].id : '';
    if (initial) {
      $('#project').value = initial === '@workspace' ? '' : initial;
      document
        .querySelectorAll('.scope')
        .forEach((button) => button.classList.toggle('active', button.dataset.project === initial));
    }
    return loadGraph(initial);
  });
})();
