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
    root.classList.toggle('dark', resolved === 'dark');
    if (color) color.content = resolved === 'dark' ? '#081321' : '#e6f0f6';
    document.querySelectorAll('[data-theme-control]').forEach((control) => {
      control.value = mode;
    });
    document.querySelectorAll('[data-theme-toggle]').forEach((button) => {
      button.setAttribute(
        'aria-label',
        `Switch to ${resolved === 'dark' ? 'light' : 'dark'} theme`
      );
      button.setAttribute('aria-pressed', String(resolved === 'dark'));
      button.dataset.state = resolved;
    });
    if (changed) root.dispatchEvent(new Event('toksmart-themechange'));
  }

  apply();
  document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.theme-control').forEach((control) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'sun-moon-toggle';
      button.dataset.themeToggle = '';
      button.innerHTML = `<span class="toggle-night" aria-hidden="true"><i></i><i></i><i></i><i></i></span><span class="toggle-day" aria-hidden="true"></span><svg class="toggle-moon" aria-hidden="true" viewBox="0 0 24 24"><path d="M20.8 15.4A9 9 0 0 1 8.6 3.2 9 9 0 1 0 20.8 15.4Z" fill="currentColor"/></svg><svg class="toggle-sun" aria-hidden="true" viewBox="0 0 24 24"><circle cx="12" cy="12" r="4" fill="currentColor"/><path d="M12 1v2m0 18v2M1 12h2m18 0h2M4.2 4.2l1.5 1.5m12.6 12.6 1.5 1.5m0-15.6-1.5 1.5M5.7 18.3l-1.5 1.5" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>`;
      control.insertAdjacentElement('afterend', button);
      control.hidden = true;
    });
    apply();
  });
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
  document.addEventListener('click', (event) => {
    const button = event.target.closest('[data-theme-toggle]');
    if (!button) return;
    const next = root.dataset.theme === 'dark' ? 'light' : 'dark';
    if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      const fade = document.createElement('style');
      fade.textContent = `body, body :not(.sun-moon-toggle):not(.sun-moon-toggle *) { transition-property: color, background-color, border-color, fill, stroke !important; transition-duration: 550ms !important; }`;
      document.head.appendChild(fade);
      setTimeout(() => fade.remove(), 650);
    }
    mode = next;
    try {
      localStorage.setItem(storageKey, mode);
    } catch {
      // The new theme still applies without browser storage.
    }
    apply();
  });
  window.addEventListener('storage', (event) => {
    if (event.key !== storageKey && event.key !== null) return;
    mode = normalize(event.newValue);
    apply();
  });
})();
