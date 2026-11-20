import { copy, waapi } from './vendor/desktop-components.js';

const command = document.getElementById('launch-command');
const copyButton = document.querySelector('.copy-button');
const copyHint = document.getElementById('step-1-badge');
let resetCopy;

copyButton.addEventListener('click', async () => {
  clearTimeout(resetCopy);
  if (!(await copy(command.textContent.trim()))) {
    const selection = window.getSelection();
    if (selection) {
      const range = document.createRange();
      range.selectNodeContents(command);
      selection.removeAllRanges();
      selection.addRange(range);
    }
    copyButton.classList.remove('copied');
    copyButton.textContent = 'Copy';
    copyHint.textContent = selection
      ? 'Command selected. Copy it manually.'
      : 'Select and copy the command from the terminal box.';
    return;
  }

  copyButton.classList.add('copied');
  copyButton.textContent = 'Copied';
  copyHint.textContent = 'Command copied.';
  resetCopy = setTimeout(() => {
    copyButton.classList.remove('copied');
    copyButton.textContent = 'Copy';
    copyHint.textContent = '';
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
