// LazyToken Local Server Auto-Connect & UI Controller
(() => {
  'use strict';

  const DEFAULT_PORT = 8765;
  const POLL_INTERVAL = 1000;
  const STORAGE_KEY = 'lazytoken_connected';
  const ENDPOINTS = [
    `http://127.0.0.1:${DEFAULT_PORT}/api/health`,
    `http://localhost:${DEFAULT_PORT}/api/health`,
    `http://127.0.0.1:${DEFAULT_PORT}/api/projects`
  ];

  let isConnected = false;
  let consecutiveFailures = 0;
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

  // --- Fast Concurrent Endpoint Ping ---
  function pingEndpoint(url) {
    return new Promise((resolve, reject) => {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 650);

      fetch(url, {
        method: 'GET',
        mode: 'cors',
        cache: 'no-store',
        signal: controller.signal
      })
        .then((res) => {
          clearTimeout(timeoutId);
          if (res.ok) resolve(url);
          else reject(new Error('Non-200 response'));
        })
        .catch((err) => {
          clearTimeout(timeoutId);
          reject(err);
        });
    });
  }

  // --- Server Health Polling ---
  async function checkServer() {
    try {
      const winningUrl = await Promise.any(ENDPOINTS.map((url) => pingEndpoint(url)));
      consecutiveFailures = 0;
      handleServerFound(winningUrl, false);
    } catch {
      consecutiveFailures++;
      // If server was marked connected but fails repeatedly, revert
      if (isConnected && consecutiveFailures >= 3) {
        handleServerLost();
      }
    }
  }

  function handleServerFound(url, isFirstDiscovery = false) {
    isConnected = true;
    try {
      localStorage.setItem(STORAGE_KEY, 'true');
      localStorage.setItem('lazytoken_last_seen', Date.now().toString());
    } catch (e) {}

    document.documentElement.classList.add('server-connected');

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

    // Step 3
    const step3Row = document.getElementById('step-3');
    const step3Indicator = document.getElementById('step-3-indicator');
    const step3Title = document.getElementById('step-3-title');
    const step3Desc = document.getElementById('step-3-description');

    if (step3Row) {
      step3Row.classList.remove('step-muted');
      step3Row.classList.add('step-connected');
    }

    if (step3Indicator) {
      step3Indicator.classList.remove('badge-muted');
      step3Indicator.classList.add('badge-purple', 'checked');
    }

    if (step3Title) {
      step3Title.textContent = 'Knowledge graph connected';
      step3Title.classList.remove('text-muted');
      step3Title.classList.add('text-white');
    }

    if (step3Desc) {
      step3Desc.textContent = 'Dashboard is ready on port 8765.';
    }

    // Only auto-redirect on the very first live detection, not on static refresh
    if (isFirstDiscovery) {
      if (step3Title) step3Title.textContent = 'Opening knowledge graph...';
      if (step3Desc) step3Desc.textContent = 'Redirecting to your local LazyToken dashboard...';
      setTimeout(() => {
        window.location.href = `http://127.0.0.1:${DEFAULT_PORT}/`;
      }, 1000);
    }
  }

  function handleServerLost() {
    isConnected = false;
    try {
      localStorage.removeItem(STORAGE_KEY);
    } catch (e) {}

    document.documentElement.classList.remove('server-connected');

    const step2Indicator = document.getElementById('step-2-indicator');
    const step2Title = document.getElementById('step-2-title');
    const listeningBox = document.getElementById('listening-box');
    const listeningPrimary = document.getElementById('listening-primary');
    const listeningSecondary = document.getElementById('listening-secondary');

    if (step2Indicator) {
      step2Indicator.classList.add('badge-purple');
      step2Indicator.classList.remove('badge-green', 'checked');
    }

    if (step2Title) {
      step2Title.textContent = 'Waiting for server to start';
      step2Title.classList.add('text-white');
      step2Title.classList.remove('text-green');
    }

    if (listeningBox) {
      listeningBox.classList.remove('connected');
    }

    if (listeningPrimary) {
      listeningPrimary.textContent = 'Listening for server ...';
    }

    if (listeningSecondary) {
      listeningSecondary.textContent = 'Will auto-connect when detected';
    }

    const step3Row = document.getElementById('step-3');
    const step3Indicator = document.getElementById('step-3-indicator');
    const step3Title = document.getElementById('step-3-title');
    const step3Desc = document.getElementById('step-3-description');

    if (step3Row) {
      step3Row.classList.add('step-muted');
      step3Row.classList.remove('step-connected');
    }

    if (step3Indicator) {
      step3Indicator.classList.add('badge-muted');
      step3Indicator.classList.remove('badge-purple', 'checked');
    }

    if (step3Title) {
      step3Title.textContent = 'Auto-connects and opens the graph';
      step3Title.classList.add('text-muted');
      step3Title.classList.remove('text-white');
    }

    if (step3Desc) {
      step3Desc.textContent = 'No refresh needed — the page detects the server automatically.';
    }
  }

  // --- Initialize ---
  document.addEventListener('DOMContentLoaded', () => {
    setupCopyButtons();

    // Check if previously connected in localStorage for instant render on refresh
    let wasConnected = false;
    try {
      wasConnected = localStorage.getItem(STORAGE_KEY) === 'true';
    } catch (e) {}

    if (wasConnected) {
      handleServerFound(`http://127.0.0.1:${DEFAULT_PORT}/`, false);
    }

    const launchBtn = document.getElementById('launch-btn');
    const statusTip = document.getElementById('status-tip');

    if (launchBtn) {
      launchBtn.addEventListener('click', async (e) => {
        if (isConnected) return; // Allow direct navigation

        try {
          const winningUrl = await Promise.any(ENDPOINTS.map((url) => pingEndpoint(url)));
          handleServerFound(winningUrl, false);
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

    // Verify or poll server
    checkServer();
    pollTimer = setInterval(checkServer, POLL_INTERVAL);
  });
})();
