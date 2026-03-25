/**
 * Preload script dla Electron <webview> z embedem Tidal.
 * Uruchamiany w kontekście embed.tidal.com – klika Play automatycznie.
 * Użycie: <webview src="https://embed.tidal.com/tracks/123" preload="tidal-embed-preload.js"></webview>
 *
 * Wymaga: zamiana iframe na webview w Electron (BUILD_JAKO_APLIKACJA.md).
 * W trybie Flask (przeglądarka) – nadal potrzebny Tampermonkey + userscript.
 */
(function() {
  'use strict';

  function tryClickPlay() {
    const selectors = [
      'button[aria-label="Play"]',
      'button[aria-label="Odtwórz"]',
      'button[title="Play"]',
      'button[title="Odtwórz"]',
      '[aria-label="Play"]',
      '[aria-label="Odtwórz"]',
      '[data-testid="play-button"]',
      '[data-testid="play"]',
      '.play-button',
      'button.play',
      '[class*="play"]',
      'button[class*="Play"]',
      '[role="button"][class*="play"]',
      '[role="button"][class*="Play"]',
    ];
    for (const sel of selectors) {
      try {
        const btn = document.querySelector(sel);
        if (btn && btn.offsetParent !== null && !btn.disabled && !btn.getAttribute('aria-disabled')) {
          btn.click();
          return true;
        }
      } catch (_) {}
    }
    const clickables = document.querySelectorAll('button, [role="button"], [class*="play"]');
    for (const el of clickables) {
      const text = (el.textContent || '').toLowerCase();
      const aria = (el.getAttribute('aria-label') || '').toLowerCase();
      const cls = (el.className || '').toLowerCase();
      if ((text.includes('play') || aria.includes('play') || text.includes('odtwórz') || aria.includes('odtwórz') || cls.includes('play')) &&
          el.offsetParent !== null && !el.disabled) {
        el.click();
        return true;
      }
    }
    return false;
  }

  function attempt() {
    if (tryClickPlay()) return;
    [100, 300, 600, 1000, 1500, 2500, 4000].forEach(ms => setTimeout(tryClickPlay, ms));
  }

  if (document.readyState === 'complete') {
    attempt();
  } else {
    window.addEventListener('load', attempt);
  }
  document.addEventListener('DOMContentLoaded', attempt);
  const observer = new MutationObserver(() => { tryClickPlay(); });
  try {
    observer.observe(document.body || document.documentElement, { childList: true, subtree: true });
    setTimeout(() => observer.disconnect(), 8000);
  } catch (_) {}
})();
