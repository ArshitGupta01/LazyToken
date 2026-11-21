(() => {
  'use strict';
  if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches && window.Lenis) {
    new window.Lenis({ autoRaf: true, anchors: true });
  }
  const button = document.querySelector('[data-copy]');
  const feedback = document.getElementById('command-feedback');
  button?.addEventListener('click', async () => {
    const command = button.dataset.copy;
    try {
      await navigator.clipboard.writeText(command);
      feedback.textContent = 'Command copied. Paste it into your terminal.';
      button.textContent = 'Copied';
    } catch {
      const selection = window.getSelection();
      const range = document.createRange();
      range.selectNodeContents(button.previousElementSibling);
      selection?.removeAllRanges();
      selection?.addRange(range);
      feedback.textContent = 'Command selected. Copy it manually.';
    }
    setTimeout(() => {
      button.textContent = 'Copy';
    }, 2300);
  });
})();
