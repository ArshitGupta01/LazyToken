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

  function start() {
    if (
      new URLSearchParams(window.location.search).get('desktop') !== '1' &&
      (/Mobi|Android|iPhone|iPad|iPod/i.test(navigator.userAgent) ||
        (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1))
    ) {
      window.location.replace('mobile.html');
      return;
    }
    checkServer();
    setInterval(checkServer, 3000);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
