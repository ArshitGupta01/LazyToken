// Check the local service while keeping the setup page visible.
(() => {
  'use strict';

  const HEALTH_URL = 'http://127.0.0.1:8765/api/health';
  const POLL_INTERVAL = 4000;
  let checking = false;

  function start() {
    if (
      new URLSearchParams(window.location.search).get('desktop') !== '1' &&
      (/Mobi|Android|iPhone|iPad|iPod/i.test(navigator.userAgent) ||
        (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1))
    ) {
      window.location.replace('mobile.html');
      return;
    }

    const card = document.getElementById('server-status');
    if (!card) return;
    const state = document.getElementById('server-state');
    const detail = document.getElementById('server-detail');
    const ping = document.getElementById('server-ping');
    const checked = document.getElementById('server-checked');
    const retry = document.getElementById('check-server');
    const clock = new Intl.DateTimeFormat(undefined, { timeStyle: 'medium' });

    function updateStatus(mode, title, description, latency = '—') {
      card.dataset.state = mode;
      if (state.textContent !== title) state.textContent = title;
      if (detail.textContent !== description) detail.textContent = description;
      if (ping.textContent !== latency) ping.textContent = latency;
      checked.textContent = clock.format(new Date());
    }

    async function checkServer() {
      if (checking) return;
      checking = true;
      retry.disabled = true;
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 2500);
      const started = performance.now();
      try {
        const response = await fetch(HEALTH_URL, {
          mode: 'cors',
          targetAddressSpace: 'loopback',
          cache: 'no-store',
          signal: controller.signal
        });
        const data = response.ok ? await response.json().catch(() => null) : null;
        if (controller.signal.aborted) throw new Error('Timed out');
        if (
          (data?.service === 'toksmart' || data?.service === 'lazytoken') &&
          (data.status == null || data.status === 'ok')
        ) {
          const elapsed = Math.round(performance.now() - started);
          const version = typeof data.version === 'string' ? ' v' + data.version : '';
          updateStatus(
            'online',
            'Server ready',
            'TokSmart' + version + ' is ready to open.',
            elapsed ? elapsed + ' ms' : '<1 ms'
          );
        } else {
          updateStatus(
            'unexpected',
            'Unexpected response',
            'Port 8765 responded, but TokSmart did not report a healthy server. Check the address in your terminal.'
          );
        }
      } catch {
        updateStatus(
          'waiting',
          'Waiting for server',
          controller.signal.aborted
            ? 'The check timed out. TokSmart may still be starting. Retrying automatically.'
            : 'Run the launch command or check local network access. Retrying automatically.'
        );
      } finally {
        clearTimeout(timeout);
        retry.disabled = false;
        checking = false;
      }
    }

    retry.addEventListener('click', checkServer);
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden) checkServer();
    });
    checkServer();
    setInterval(() => {
      if (!document.hidden) checkServer();
    }, POLL_INTERVAL);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
