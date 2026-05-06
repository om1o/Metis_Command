/**
 * Metis Wordmark click-to-refresh.
 *
 * Delegated so it works for any .metis-mark button, in any page, even
 * if the markup is added dynamically. Modifier-clicks (cmd, ctrl, shift,
 * middle button) are allowed through so power users can still open the
 * page in a new tab if they want.
 */
(function () {
  'use strict';
  document.addEventListener('click', function (e) {
    var mark = e.target.closest && e.target.closest('.metis-mark');
    if (!mark) return;
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button === 1) return;
    e.preventDefault();
    // Quick visual ack before reload (browser usually shows a flash anyway,
    // but this gives the press some weight on slow networks).
    mark.style.opacity = '0.6';
    location.reload();
  }, false);
})();
