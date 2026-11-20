(() => {
  const storageKey = 'toksmart_theme';
  const root = document.documentElement;
  const defaultMode = root.dataset.defaultTheme === 'dark' ? 'dark' : 'system';
  const system = window.matchMedia('(prefers-color-scheme: dark)');
  const color = document.querySelector('meta[name="theme-color"]');

  function normalize(value) {
    return value === 'light' || value === 'dark' || value === 'system' ? value : defaultMode;
  }

  let mode = defaultMode;
  try {
    mode = normalize(localStorage.getItem(storageKey));
  } catch {
    // Keep the page default when browser storage is unavailable.
  }

  function apply() {
    const resolved = mode === 'system' ? (system.matches ? 'dark' : 'light') : mode;
    const changed = root.dataset.theme !== resolved;
    root.dataset.theme = resolved;
    if (color) color.content = resolved === 'dark' ? '#0e1211' : '#edf1e9';
    document.querySelectorAll('[data-theme-control]').forEach((control) => {
      control.value = mode;
    });
    if (changed) root.dispatchEvent(new Event('toksmart-themechange'));
  }

  apply();
  document.addEventListener('DOMContentLoaded', apply);
  system.addEventListener('change', apply);
  document.addEventListener('change', (event) => {
    if (!event.target.matches('[data-theme-control]')) return;
    mode = normalize(event.target.value);
    try {
      localStorage.setItem(storageKey, mode);
    } catch {
      // The chosen theme still applies to this page.
    }
    apply();
  });
  window.addEventListener('storage', (event) => {
    if (event.key !== storageKey && event.key !== null) return;
    mode = normalize(event.newValue);
    apply();
  });
})();
