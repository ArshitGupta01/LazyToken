// LazyToken Local Server Auto-Connect & UI Controller
(() => {
  'use strict';

  const DEFAULT_PORT = 8765;
  const POLL_INTERVAL = 1200;
  const ENDPOINTS = [
    `http://127.0.0.1:${DEFAULT_PORT}/api/health`,
    `http://localhost:${DEFAULT_PORT}/api/health`,
    `http://127.0.0.1:${DEFAULT_PORT}/api/projects`
  ];

  let isConnected = false;
  let pollTimer = null;

  // --- Copy Buttons ---
  function setupCopyButtons() {
    const copyButtons = document.querySelectorAll('.copy-button');
    const step1Badge = document.getElementById('step-1-badge');

    copyButtons.forEach((btn) => {
      btn.addEventListener('click', async () => {
        const cmd = btn.getAttribute('data-command');
        if (!cmd) return;

        try {
          await navigator.clipboard.writeText(cmd);
          btn.classList.add('copied');

          if (step1Badge) {
            step1Badge.textContent = 'COPIED';
            step1Badge.classList.add('active');
          }

          setTimeout(() => {
            btn.classList.remove('copied');
            if (step1Badge) {
              step1Badge.textContent = 'DONE';
              step1Badge.classList.remove('active');
            }
          }, 2000);
        } catch {
          // Fallback if clipboard API restricted
          const ta = document.createElement('textarea');
          ta.value = cmd;
          ta.style.position = 'fixed';
          ta.style.opacity = '0';
          document.body.appendChild(ta);
          ta.select();
          try {
            document.execCommand('copy');
            btn.classList.add('copied');
            setTimeout(() => btn.classList.remove('copied'), 2000);
          } finally {
            document.body.removeChild(ta);
          }
        }
      });
    });
  }

  // --- Server Health Polling ---
  async function checkServer() {
    if (isConnected) return;

    for (const url of ENDPOINTS) {
      try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 950);

        const res = await fetch(url, {
          method: 'GET',
          mode: 'cors',
          cache: 'no-store',
          signal: controller.signal
        });

        clearTimeout(timeoutId);

        if (res.ok) {
          handleServerFound(url);
          return;
        }
      } catch {
        // Continue to next endpoint or wait for next poll tick
      }
    }
  }

  function handleServerFound(url) {
    if (isConnected) return;
    isConnected = true;

    if (pollTimer) clearInterval(pollTimer);

    // Update Step 2: Connected
    const step2Indicator = document.getElementById('step-2-indicator');
    const step2Title = document.getElementById('step-2-title');
    const listeningBox = document.getElementById('listening-box');
    const listeningPrimary = document.getElementById('listening-primary');
    const listeningSecondary = document.getElementById('listening-secondary');

    if (step2Indicator) {
      step2Indicator.classList.remove('badge-purple');
      step2Indicator.classList.add('badge-green', 'checked');
    }

    if (step2Title) {
      step2Title.textContent = 'Server connected';
      step2Title.classList.remove('text-white');
      step2Title.classList.add('text-green');
    }

    if (listeningBox) {
      listeningBox.classList.add('connected');
    }

    if (listeningPrimary) {
      listeningPrimary.textContent = 'Connected to local server';
    }

    if (listeningSecondary) {
      listeningSecondary.textContent = 'Server detected on port 8765';
    }

    // Update Step 3: Auto-connect / Opening graph
    const step3Row = document.getElementById('step-3');
    const step3Indicator = document.getElementById('step-3-indicator');
    const step3Title = document.getElementById('step-3-title');
    const step3Desc = document.getElementById('step-3-description');
    const actionFallback = document.getElementById('action-fallback');

    if (step3Row) {
      step3Row.classList.remove('step-muted');
      step3Row.classList.add('step-connected');
    }

    if (step3Indicator) {
      step3Indicator.classList.remove('badge-muted');
      step3Indicator.classList.add('badge-purple', 'checked');
    }

    if (step3Title) {
      step3Title.textContent = 'Opening knowledge graph...';
      step3Title.classList.remove('text-muted');
      step3Title.classList.add('text-white');
    }

    if (step3Desc) {
      step3Desc.textContent = 'Redirecting to your local LazyToken dashboard...';
    }

    if (actionFallback) {
      actionFallback.style.display = 'block';
    }

    // Redirect after brief visual transition
    setTimeout(() => {
      window.location.href = `http://127.0.0.1:${DEFAULT_PORT}/`;
    }, 1200);
  }

  // --- Initialize ---
  document.addEventListener('DOMContentLoaded', () => {
    setupCopyButtons();

    const launchBtn = document.getElementById('launch-btn');
    const statusTip = document.getElementById('status-tip');

    if (launchBtn) {
      launchBtn.addEventListener('click', async (e) => {
        if (isConnected) return;

        try {
          const controller = new AbortController();
          const tid = setTimeout(() => controller.abort(), 700);
          const res = await fetch(`http://127.0.0.1:${DEFAULT_PORT}/api/health`, {
            signal: controller.signal,
            mode: 'cors',
            cache: 'no-store'
          });
          clearTimeout(tid);
          if (res.ok) {
            handleServerFound(`http://127.0.0.1:${DEFAULT_PORT}/`);
            return;
          }
        } catch {
          e.preventDefault();
          if (statusTip) {
            statusTip.textContent =
              '⚠️ Local server not running yet. Run "npx lazytoken@latest serve" in your terminal first.';
            statusTip.classList.add('error');
            setTimeout(() => {
              statusTip.textContent = '';
              statusTip.classList.remove('error');
            }, 4000);
          }
        }
      });
    }

    // Start initial check immediately, then periodically
    checkServer();
    pollTimer = setInterval(checkServer, POLL_INTERVAL);
  });
})();
