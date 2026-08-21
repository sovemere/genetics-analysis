/*
 * Theme, applied before the first paint (roadmap M4.8).
 *
 * The one script on this page that is **not** deferred, and the only reason is timing: it
 * writes `data-theme` onto `<html>` so the stylesheet resolves the right palette on the
 * first paint. Deferred, it would run after the page had already been drawn in the system
 * theme, and every load under an explicit theme would flash the other one.
 *
 * That makes it a render-blocking script on every page, so it stays this small and does
 * nothing else. It also sets `data-js`, which is what reveals the theme toggle: a control
 * that needs scripting and renders anyway is a control that silently does nothing.
 *
 * `localStorage` is wrapped because it throws rather than returning null when storage is
 * disabled or the page is in a partitioned context -- and a page that failed to render
 * because it could not read a colour preference would be a spectacular way to lose a
 * dashboard.
 */
(function () {
  var root = document.documentElement;
  root.setAttribute('data-js', 'on');
  try {
    var saved = window.localStorage.getItem('genetics-theme');
    if (saved === 'light' || saved === 'dark') {
      root.setAttribute('data-theme', saved);
    }
  } catch (error) {
    /* Storage unavailable. The system preference still applies through CSS. */
  }
})();
