import { copy, waapi } from './vendor/desktop-components.js';

const copyHint = document.getElementById('step-1-badge');
let resetCopy;
let copyAttempt = 0;
let activeCopy;

document.querySelector('.setup-instructions').addEventListener('click', async (event) => {
  const button = event.target.closest('.copy-button');
  if (!button) return;
  const attempt = ++copyAttempt;
  const command = button.parentElement.querySelector('code');
  clearTimeout(resetCopy);
  if (activeCopy) activeCopy.textContent = 'Copy';
  activeCopy = button;
  const copied = await copy(command.textContent.trim());
  if (attempt !== copyAttempt) return;
  if (!copied) {
    const selection = window.getSelection();
    if (selection) {
      const range = document.createRange();
      range.selectNodeContents(command);
      selection.removeAllRanges();
      selection.addRange(range);
    }
    copyHint.textContent = selection
      ? 'Command selected. Copy it manually.'
      : 'Select and copy the command from the terminal box.';
    return;
  }

  button.textContent = 'Copied';
  copyHint.textContent = 'Command copied.';
  resetCopy = setTimeout(() => {
    button.textContent = 'Copy';
    copyHint.textContent = '';
    activeCopy = null;
  }, 2000);
});

const preview = document.querySelector('.desktop-preview');
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
let transition;

preview.addEventListener('tab-container-changed', (event) => {
  transition?.cancel();
  if (reducedMotion.matches || typeof event.panel.animate !== 'function') return;
  transition = waapi.animate(event.panel, {
    opacity: [0.72, 1],
    duration: 160,
    ease: 'outQuad'
  });
});

const sample = document.querySelector('.sample-graph');
const evidence = sample.querySelector('.sample-evidence');
const file = evidence.querySelector('strong');
const dependency = evidence.querySelector('.evidence-meta > span');
const source = evidence.querySelector('code');
const connections = sample.querySelectorAll('.sample-edges path');
const files = {
  router: ['router.py:1', 'Imports auth.py', 'from auth import AuthMiddleware'],
  auth: ['auth.py:1', 'Imports sessions.py', 'from sessions import SessionStore'],
  sessions: ['sessions.py:1', 'Imports storage.py', 'import storage'],
  storage: ['storage.py:1', 'Imports sqlite3', 'import sqlite3']
};

function showEvidence(selectedFile) {
  [file.textContent, dependency.textContent, source.textContent] = files[selectedFile];
  connections.forEach((path) => {
    path.classList.toggle('is-active', path.dataset.connects.split(' ').includes(selectedFile));
  });
}

sample.addEventListener('change', (event) => {
  if (event.target.name === 'sample-file') showEvidence(event.target.value);
});

window.addEventListener('pageshow', () => {
  showEvidence(sample.querySelector('input:checked').value);
});
