// The hosted page only detects the local service and opens its private dashboard.
(() => {
  'use strict';

  const HEALTH_URL = 'http://127.0.0.1:8765/api/health';
  let checking = false;

  async function checkServer() {
    if (checking) return;
    checking = true;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 2500);
    try {
      const response = await fetch(HEALTH_URL, {
        mode: 'cors',
        targetAddressSpace: 'loopback',
        cache: 'no-store',
        signal: controller.signal
      });
      if (!response.ok) return;
      const data = await response.json();
      if (data.service === 'toksmart' || data.service === 'lazytoken') {
        window.location.replace('http://127.0.0.1:8765/');
      }
    } catch {
      // The server is stopped or the browser has not allowed local access yet.
    } finally {
      clearTimeout(timeout);
      checking = false;
    }
  }

  function setupCopyButtons() {
    const badge = document.getElementById('step-1-badge');
    document.querySelectorAll('.copy-button').forEach((button) => {
      button.addEventListener('click', async () => {
        const command = button.getAttribute('data-command');
        if (!command) return;
        let copied = false;
        try {
          await navigator.clipboard.writeText(command);
          copied = true;
        } catch {
          const input = document.createElement('textarea');
          input.value = command;
          input.style.position = 'fixed';
          input.style.opacity = '0';
          document.body.appendChild(input);
          input.select();
          try {
            copied = document.execCommand('copy');
          } catch {
            copied = false;
          } finally {
            input.remove();
          }
        }
        if (!copied) {
          const selection = window.getSelection();
          if (selection) {
            const range = document.createRange();
            range.selectNodeContents(document.getElementById('launch-command'));
            selection.removeAllRanges();
            selection.addRange(range);
          }
          if (badge) {
            badge.textContent = selection
              ? 'Command selected. Copy it manually.'
              : 'Select and copy the command from the terminal box.';
          }
          return;
        }
        button.classList.add('copied');
        button.textContent = 'Copied';
        if (badge) badge.textContent = 'Command copied.';
        setTimeout(() => {
          button.classList.remove('copied');
          button.textContent = 'Copy';
          if (badge) badge.textContent = '';
        }, 2000);
      });
    });
  }

  function setupPreview() {
    const image = document.getElementById('dashboard-preview');
    const fullSize = document.getElementById('preview-full-size');
    const caption = document.getElementById('preview-caption');
    if (!image || !fullSize || !caption) return;

    const views = {
      graph: {
        src: 'desktop-preview.webp',
        alt: 'TokSmart knowledge graph with the Session store node selected and its relationships in the inspector.',
        caption: 'Graph and node inspector on an example repository.'
      },
      search: {
        src: 'search-preview.webp',
        alt: 'TokSmart code search for SessionStore showing the matching symbol and source file.',
        caption: 'Code search for SessionStore in the same repository.'
      }
    };
    const controls = document.querySelectorAll('[data-preview]');
    controls.forEach((control) => {
      control.addEventListener('click', () => {
        const view = views[control.dataset.preview];
        image.src = view.src;
        fullSize.href = view.src;
        image.alt = view.alt;
        caption.textContent = view.caption;
        controls.forEach((button) => {
          button.setAttribute('aria-pressed', String(button === control));
        });
      });
    });
  }

  function start() {
    setupCopyButtons();
    if (
      new URLSearchParams(window.location.search).get('desktop') !== '1' &&
      (/Mobi|Android|iPhone|iPad|iPod/i.test(navigator.userAgent) ||
        (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1))
    ) {
      window.location.replace('mobile.html');
      return;
    }
    setupPreview();
    checkServer();
    setInterval(checkServer, 3000);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
