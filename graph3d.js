import * as THREE from './vendor/three.module.js';
import { OrbitControls } from './vendor/OrbitControls.js';

// Loaded only when a human opens the 3D view; it never runs in the MCP process.
export function createGraph3D(host, { onSelect, onHover, color, onUnavailable }) {
  const renderer = new THREE.WebGLRenderer({
    antialias: true,
    alpha: true,
    powerPreference: 'high-performance'
  });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
  renderer.setClearColor(0x1d1c18, 0);
  renderer.domElement.setAttribute('aria-label', 'Interactive 3D knowledge graph');
  function onContextLost(event) {
    event.preventDefault();
    active = false;
    cancelAnimationFrame(frame);
    onUnavailable?.();
  }
  renderer.domElement.addEventListener('webglcontextlost', onContextLost);
  const labelLayer = document.createElement('div');
  labelLayer.className = 'graph3d-labels';
  host.replaceChildren(renderer.domElement, labelLayer);
  const scene = new THREE.Scene(),
    camera = new THREE.PerspectiveCamera(43, 1, 0.1, 5000);
  camera.position.set(0, 85, 720);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = !matchMedia('(prefers-reduced-motion: reduce)').matches;
  controls.dampingFactor = 0.08;
  controls.minDistance = 130;
  controls.maxDistance = 1800;
  controls.screenSpacePanning = true;
  const group = new THREE.Group();
  scene.add(group);
  // A faint reference grid is decorative; it does not represent graph records.
  const grid = new THREE.GridHelper(1200, 24, 0x887a68, 0x645b4c);
  grid.position.y = -250;
  grid.material.transparent = true;
  grid.material.opacity = 0.27;
  grid.material.depthWrite = false;
  scene.add(grid);
  const raycaster = new THREE.Raycaster(),
    pointer = new THREE.Vector2();
  const sphere = new THREE.SphereGeometry(1, 16, 12);
  let nodeMeshes = [],
    labels = [],
    edgeLines = null,
    renderedEdges = [],
    frame = 0,
    active = false,
    signature = '',
    selected = null,
    hovered = null,
    down = null,
    target = null,
    resizeObserver = null;
  const reduce = matchMedia('(prefers-reduced-motion: reduce)');
  scene.add(new THREE.AmbientLight(0xe0d5c5, 1.1));
  const keyLight = new THREE.PointLight(0xffecd7, 180000);
  keyLight.position.set(150, 220, 480);
  scene.add(keyLight);
  function clear() {
    for (const mesh of nodeMeshes) {
      group.remove(mesh);
      mesh.material.dispose();
    }
    nodeMeshes = [];
    for (const label of labels) label.remove();
    labels = [];
    if (edgeLines) {
      group.remove(edgeLines);
      edgeLines.geometry.dispose();
      edgeLines.material.dispose();
      edgeLines = null;
    }
    renderedEdges = [];
  }
  function resize() {
    const { width, height } = host.getBoundingClientRect();
    if (!width || !height) return;
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    renderOnce();
  }
  function positionFor(node, width, height) {
    return new THREE.Vector3(
      (node.x - width / 2) * 0.9,
      -(node.y - height / 2) * 0.9,
      (node.z || 0) * 0.7
    );
  }
  function setState({ nodes, edges, selected: pick, hovered: over, width, height, visuals }) {
    selected = pick;
    hovered = over;
    const key = JSON.stringify([
      nodes.map((n) => [n.id, n.name, n.kind, Math.round(n.x), Math.round(n.y)]),
      edges.map((e) => [e.a.id, e.b.id, e.relation, e.scope])
    ]);
    if (key !== signature) {
      signature = key;
      clear();
      const positions = new Map();
      for (const n of nodes) {
        const pos = positionFor(n, width, height);
        positions.set(n.id, pos);
        const nodeColor = new THREE.Color(color(n.kind));
        const material = new THREE.MeshPhongMaterial({
          color: nodeColor.clone().multiplyScalar(0.61),
          emissive: nodeColor,
          emissiveIntensity: 0.3,
          shininess: 22,
          specular: 0xffe6c4
        });
        const mesh = new THREE.Mesh(sphere, material);
        const radius = Math.max(7, Math.min(14, n.r || 9));
        mesh.position.copy(pos);
        mesh.scale.setScalar(radius);
        mesh.userData.node = n;
        group.add(mesh);
        nodeMeshes.push(mesh);
        const label = document.createElement('button');
        label.type = 'button';
        label.className = 'graph3d-label';
        label.textContent = n.name;
        label.setAttribute('aria-label', `Inspect ${n.name}`);
        label.addEventListener('click', () => {
          onSelect(n);
          focus(n);
        });
        labelLayer.append(label);
        labels.push(label);
      }
      const coords = [],
        colors = [];
      for (const e of edges) {
        const a = positions.get(e.a.id),
          b = positions.get(e.b.id);
        if (!a || !b) continue;
        coords.push(a.x, a.y, a.z, b.x, b.y, b.z);
        const c = new THREE.Color(e.scope === '*' ? visuals.sharedEdge : visuals.projectEdge);
        colors.push(c.r, c.g, c.b, c.r, c.g, c.b);
        renderedEdges.push(e);
      }
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute('position', new THREE.Float32BufferAttribute(coords, 3));
      geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));
      edgeLines = new THREE.LineSegments(
        geometry,
        new THREE.LineBasicMaterial({
          vertexColors: true,
          transparent: true,
          opacity: 0.65,
          depthWrite: false
        })
      );
      group.add(edgeLines);
    }
    const focused = hovered || selected;
    const neighbors = new Set(
      focused
        ? renderedEdges
            .filter((e) => e.a.id === focused.id || e.b.id === focused.id)
            .flatMap((e) => [e.a.id, e.b.id])
        : []
    );
    for (const mesh of nodeMeshes) {
      const id = mesh.userData.node.id,
        isSelected = selected && id === selected.id,
        isHovered = hovered && id === hovered.id,
        dim = focused && id !== focused.id && !neighbors.has(id);
      mesh.scale.setScalar(
        (mesh.userData.node.r || 9) * (isSelected ? 1.35 : isHovered ? 1.15 : 1)
      );
      const tint = color(mesh.userData.node.kind);
      mesh.material.color.set(tint).multiplyScalar(dim ? 0.2 : 0.61);
      mesh.material.emissive.set(tint);
      mesh.material.emissiveIntensity = dim ? 0.06 : isSelected ? 0.5 : 0.3;
    }
    if (edgeLines) {
      const attribute = edgeLines.geometry.getAttribute('color');
      renderedEdges.forEach((edge, i) => {
        const activeEdge = focused && (edge.a.id === focused.id || edge.b.id === focused.id);
        const tint = new THREE.Color(
          activeEdge
            ? visuals.activeEdge
            : edge.scope === '*'
              ? visuals.sharedEdge
              : visuals.projectEdge
        ).multiplyScalar(focused && !activeEdge ? 0.2 : 1);
        attribute.setXYZ(i * 2, tint.r, tint.g, tint.b);
        attribute.setXYZ(i * 2 + 1, tint.r, tint.g, tint.b);
      });
      attribute.needsUpdate = true;
    }
    renderOnce();
  }
  function renderLabels() {
    const canvas = renderer.domElement,
      w = canvas.clientWidth,
      h = canvas.clientHeight,
      vector = new THREE.Vector3();
    nodeMeshes.forEach((mesh, i) => {
      const label = labels[i];
      vector.copy(mesh.position).project(camera);
      const show =
        vector.z > -1 &&
        vector.z < 1 &&
        (nodeMeshes.length <= 35 ||
          (selected && mesh.userData.node.id === selected.id) ||
          (hovered && mesh.userData.node.id === hovered.id));
      label.hidden = !show;
      if (show) {
        label.style.left = `${(vector.x * 0.5 + 0.5) * w}px`;
        label.style.top = `${(-vector.y * 0.5 + 0.5) * h + 14}px`;
        label.classList.toggle('selected', !!selected && mesh.userData.node.id === selected.id);
      }
    });
  }
  function renderOnce() {
    if (!active) return;
    renderer.render(scene, camera);
    renderLabels();
  }
  function schedule() {
    if (active && !document.hidden && !reduce.matches && !frame)
      frame = requestAnimationFrame(loop);
  }
  function loop() {
    frame = 0;
    if (!active || document.hidden) return;
    const moving = !!target;
    if (target) {
      controls.target.lerp(target, 0.12);
      if (controls.target.distanceTo(target) < 0.2) {
        controls.target.copy(target);
        target = null;
      }
    }
    const changed = controls.update();
    renderOnce();
    if (moving || changed) schedule();
  }
  function focus(node) {
    const mesh = nodeMeshes.find((m) => m.userData.node.id === node.id);
    if (!mesh) return;
    const dest = mesh.position.clone();
    if (reduce.matches) {
      controls.target.copy(dest);
      renderOnce();
    } else {
      target = dest;
      schedule();
    }
  }
  function pick(event) {
    const rect = renderer.domElement.getBoundingClientRect();
    pointer.set(
      ((event.clientX - rect.left) / rect.width) * 2 - 1,
      -((event.clientY - rect.top) / rect.height) * 2 + 1
    );
    raycaster.setFromCamera(pointer, camera);
    return raycaster.intersectObjects(nodeMeshes, false)[0]?.object.userData.node || null;
  }
  renderer.domElement.addEventListener('pointerdown', (e) => {
    down = { x: e.clientX, y: e.clientY };
  });
  renderer.domElement.addEventListener('pointerup', (e) => {
    if (down && Math.hypot(e.clientX - down.x, e.clientY - down.y) < 5) {
      const node = pick(e);
      if (node) {
        onSelect(node);
        focus(node);
      }
    }
    down = null;
  });
  renderer.domElement.addEventListener('pointermove', (e) => {
    if (down) return;
    const node = pick(e);
    if ((node?.id || null) !== (hovered?.id || null)) {
      hovered = node;
      onHover(node);
    }
    renderer.domElement.style.cursor = node ? 'pointer' : 'grab';
  });
  renderer.domElement.addEventListener('pointerleave', () => {
    hovered = null;
    onHover(null);
  });
  controls.addEventListener('change', () => {
    renderOnce();
    schedule();
  });
  function onVisibility() {
    if (!active) return;
    cancelAnimationFrame(frame);
    frame = 0;
    if (!document.hidden) {
      renderOnce();
      schedule();
    }
  }
  function onMotionChange() {
    controls.enableDamping = !reduce.matches;
    onVisibility();
  }
  document.addEventListener('visibilitychange', onVisibility);
  reduce.addEventListener('change', onMotionChange);
  resizeObserver = new ResizeObserver(resize);
  resizeObserver.observe(host);
  return {
    setState,
    focus,
    setActive(value) {
      if (active === value) {
        if (value) resize();
        return;
      }
      active = value;
      host.hidden = !value;
      if (value) {
        resize();
        renderOnce();
        schedule();
      } else {
        cancelAnimationFrame(frame);
        frame = 0;
      }
    },
    resize,
    fit() {
      if (!nodeMeshes.length) return;
      const bounds = new THREE.Box3();
      const point = new THREE.Vector3();
      for (const mesh of nodeMeshes) {
        const radius = mesh.scale.x + 8;
        bounds.expandByPoint(point.copy(mesh.position).addScalar(-radius));
        bounds.expandByPoint(point.copy(mesh.position).addScalar(radius));
      }
      const { center, radius } = bounds.getBoundingSphere(new THREE.Sphere());
      const vertical = THREE.MathUtils.degToRad(camera.fov / 2);
      const horizontal = Math.atan(Math.tan(vertical) * camera.aspect);
      const distance = (radius * 1.12) / Math.sin(Math.min(vertical, horizontal));
      const direction = camera.position.clone().sub(controls.target).normalize();
      controls.maxDistance = Math.max(1800, distance);
      controls.target.copy(center);
      camera.position
        .copy(center)
        .addScaledVector(direction, Math.max(controls.minDistance, distance));
      target = null;
      controls.update();
      renderOnce();
    },
    zoom(factor) {
      const offset = camera.position.clone().sub(controls.target).multiplyScalar(factor);
      camera.position.copy(controls.target).add(offset);
      controls.update();
      renderOnce();
    },
    dispose() {
      renderer.domElement.removeEventListener('webglcontextlost', onContextLost);
      active = false;
      cancelAnimationFrame(frame);
      document.removeEventListener('visibilitychange', onVisibility);
      reduce.removeEventListener('change', onMotionChange);
      resizeObserver.disconnect();
      clear();
      sphere.dispose();
      grid.geometry.dispose();
      grid.material.dispose();
      controls.dispose();
      renderer.dispose();
      host.replaceChildren();
    }
  };
}
