/**
 * Metis AI — Global Polish Layer
 * Usage: <script src="../polish/global-polish.js"></script>
 * Exposes: window.MetisPolish, window.toast(type, title, msg, duration)
 */
(function() {
'use strict';

const prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

/* ── DOM injection ─────────────────────────────────────────── */
function inject() {
  const html = `
    <div id="mp-dot"></div>
    <div id="mp-ring"></div>
    <div id="mp-grain"></div>
    <div id="mp-progress"></div>
    <div id="mp-transition"></div>
    <div id="mp-toasts"></div>
  `;
  document.body.insertAdjacentHTML('beforeend', html);
}
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}

function init() {
  inject();
  if (!prefersReduced) {
    initCursor();
    initGrain();
  }
  initProgress();
  initReveal();
  initTilt();
  initMagnetic();
  initCounters();
  initFloatingLabels();
  initFocusRipple();
  initNavFrost();
  initNavPill();
  initPageTransitions();
  initHamburger();
}

/* ── Cursor ────────────────────────────────────────────────── */
function initCursor() {
  const dot = document.getElementById('mp-dot');
  const ring = document.getElementById('mp-ring');
  if (!dot || !ring) return;

  let mx = 0, my = 0, rx = 0, ry = 0;
  document.addEventListener('mousemove', e => { mx = e.clientX; my = e.clientY; });
  document.addEventListener('mousedown', () => document.body.classList.add('cursor-click'));
  document.addEventListener('mouseup',   () => document.body.classList.remove('cursor-click'));

  const interactors = 'a,button,input,textarea,select,[data-mag],[data-tilt],[role=button]';
  document.addEventListener('mouseover', e => {
    if (e.target.closest(interactors)) document.body.classList.add('cursor-hover');
  });
  document.addEventListener('mouseout', e => {
    if (e.target.closest(interactors)) document.body.classList.remove('cursor-hover');
  });

  const LERP = 0.13;
  (function loop() {
    rx += (mx - rx) * LERP;
    ry += (my - ry) * LERP;
    dot.style.left  = mx + 'px';
    dot.style.top   = my + 'px';
    ring.style.left = rx + 'px';
    ring.style.top  = ry + 'px';
    requestAnimationFrame(loop);
  })();
}

/* ── Grain animation offset ────────────────────────────────── */
function initGrain() {
  /* CSS handles the animation; nothing to init */
}

/* ── Scroll progress bar ───────────────────────────────────── */
function initProgress() {
  const bar = document.getElementById('mp-progress');
  if (!bar) return;
  window.addEventListener('scroll', () => {
    const s = document.documentElement.scrollTop;
    const h = document.documentElement.scrollHeight - window.innerHeight;
    bar.style.transform = `scaleX(${h > 0 ? s / h : 0})`;
  }, { passive: true });
}

/* ── Staggered reveal via IntersectionObserver ─────────────── */
function initReveal() {
  const els = document.querySelectorAll('.mp-reveal');
  if (!els.length) return;
  const io = new IntersectionObserver(entries => {
    entries.forEach((e, i) => {
      if (e.isIntersecting) {
        const delay = parseFloat(e.target.dataset.revealDelay || 0) || 0;
        e.target.style.setProperty('--reveal-delay', delay + 'ms');
        e.target.classList.add('visible');
        io.unobserve(e.target);
      }
    });
  }, { threshold: 0.12 });

  // Auto-stagger siblings in a group
  document.querySelectorAll('[data-reveal-group]').forEach(group => {
    group.querySelectorAll('.mp-reveal').forEach((el, idx) => {
      el.dataset.revealDelay = idx * 60;
    });
  });

  els.forEach(el => io.observe(el));
}

/* ── 3D tilt ───────────────────────────────────────────────── */
function initTilt() {
  document.querySelectorAll('[data-tilt], .mp-tilt').forEach(card => {
    // Ensure shine overlay exists
    if (!card.querySelector('.mp-tilt-shine')) {
      card.style.position = 'relative';
      const shine = document.createElement('div');
      shine.className = 'mp-tilt-shine';
      card.prepend(shine);
    }
    const shine = card.querySelector('.mp-tilt-shine');
    const MAX = 12;

    card.addEventListener('mousemove', e => {
      if (prefersReduced) return;
      const r = card.getBoundingClientRect();
      const x = (e.clientX - r.left) / r.width  - 0.5;
      const y = (e.clientY - r.top)  / r.height - 0.5;
      card.style.transform = `perspective(900px) rotateY(${x * MAX}deg) rotateX(${-y * MAX * 0.7}deg) scale(1.022)`;
      card.style.boxShadow = `${-x * 22}px ${-y * 16}px 48px rgba(0,0,0,.36),0 0 0 1px rgba(255,255,255,${.04 + Math.abs(x + y) * .03})`;
      shine.style.background = `radial-gradient(circle at ${(x + .5) * 100}% ${(y + .5) * 100}%, rgba(255,255,255,.1), transparent 55%)`;
    });
    card.addEventListener('mouseleave', () => {
      card.style.transform = '';
      card.style.boxShadow = '';
      shine.style.background = '';
    });
  });
}

/* ── Magnetic buttons ──────────────────────────────────────── */
function initMagnetic() {
  document.querySelectorAll('[data-mag]').forEach(btn => {
    btn.addEventListener('mousemove', e => {
      if (prefersReduced) return;
      const r = btn.getBoundingClientRect();
      const dx = e.clientX - (r.left + r.width  / 2);
      const dy = e.clientY - (r.top  + r.height / 2);
      btn.style.transform = `translate(${dx * .18}px, ${dy * .18}px)`;
    });
    btn.addEventListener('mouseleave', () => btn.style.transform = '');
  });
}

/* ── Number counters ───────────────────────────────────────── */
function initCounters() {
  const els = document.querySelectorAll('[data-mp-count]');
  if (!els.length) return;
  const io = new IntersectionObserver(entries => {
    entries.forEach(e => {
      if (!e.isIntersecting) return;
      const el  = e.target;
      const to  = parseFloat(el.dataset.mpCount);
      const suf = el.dataset.suffix || '';
      const dec = el.dataset.decimals ? parseInt(el.dataset.decimals) : 0;
      const dur = 1600;
      const startT = performance.now();
      if (prefersReduced) { el.textContent = to.toFixed(dec) + suf; return; }
      function tick(now) {
        const t = Math.min(1, (now - startT) / dur);
        const ease = 1 - Math.pow(1 - t, 3);
        el.textContent = (ease * to).toFixed(dec) + suf;
        if (t < 1) requestAnimationFrame(tick);
      }
      requestAnimationFrame(tick);
      io.unobserve(el);
    });
  }, { threshold: 0.5 });
  els.forEach(el => io.observe(el));
}

/* ── Floating labels ───────────────────────────────────────── */
function initFloatingLabels() {
  document.querySelectorAll('.mp-field input, .mp-field textarea').forEach(input => {
    // Needs placeholder=" " to trigger :not(:placeholder-shown)
    if (!input.getAttribute('placeholder')) input.setAttribute('placeholder', ' ');
  });
}

/* ── Focus ripple ──────────────────────────────────────────── */
function initFocusRipple() {
  document.querySelectorAll('.mp-field input, .mp-field textarea').forEach(input => {
    input.addEventListener('focus', () => {
      if (prefersReduced) return;
      const parent = input.closest('.mp-field') || input.parentElement;
      const ring = document.createElement('div');
      ring.className = 'mp-focus-ring';
      parent.style.position = 'relative';
      parent.appendChild(ring);
      ring.addEventListener('animationend', () => ring.remove());
    });
  });
}

/* ── Form validation helpers ───────────────────────────────── */
window.MetisForm = {
  error(field) {
    const el = typeof field === 'string' ? document.querySelector(field) : field;
    const wrap = el.closest('.mp-field') || el.parentElement;
    wrap.classList.remove('success'); wrap.classList.add('error');
    if (!prefersReduced) {
      el.classList.remove('mp-shake');
      void el.offsetWidth; // reflow
      el.classList.add('mp-shake');
    }
  },
  success(field) {
    const el = typeof field === 'string' ? document.querySelector(field) : field;
    const wrap = el.closest('.mp-field') || el.parentElement;
    wrap.classList.remove('error'); wrap.classList.add('success');
    if (!prefersReduced) {
      const bloom = document.createElement('div');
      bloom.className = 'mp-bloom';
      wrap.style.position = 'relative';
      wrap.appendChild(bloom);
      bloom.addEventListener('animationend', () => bloom.remove());
    }
  },
  clear(field) {
    const el = typeof field === 'string' ? document.querySelector(field) : field;
    const wrap = el.closest('.mp-field') || el.parentElement;
    wrap.classList.remove('error', 'success');
  }
};

/* ── Nav frost on scroll ───────────────────────────────────── */
function initNavFrost() {
  const navs = document.querySelectorAll('nav.mp-nav-frost, .mp-nav-frost');
  if (!navs.length) return;
  const threshold = 40;
  const update = () => {
    const scrolled = window.scrollY > threshold;
    navs.forEach(n => n.classList.toggle('scrolled', scrolled));
  };
  window.addEventListener('scroll', update, { passive: true });
  update();
}

/* ── Sliding nav pill ──────────────────────────────────────── */
function initNavPill() {
  document.querySelectorAll('[data-nav-group]').forEach(nav => {
    const links = nav.querySelectorAll('a, button');
    if (!links.length) return;
    const pill = document.createElement('div');
    pill.className = 'mp-nav-pill';
    nav.style.position = 'relative';
    nav.prepend(pill);
    function movePill(el) {
      const nr = nav.getBoundingClientRect();
      const er = el.getBoundingClientRect();
      pill.style.width  = er.width  + 'px';
      pill.style.height = er.height + 'px';
      pill.style.top    = (er.top  - nr.top)  + 'px';
      pill.style.left   = (er.left - nr.left) + 'px';
      pill.style.opacity = '1';
    }
    const active = nav.querySelector('.active, [aria-current]');
    if (active) movePill(active);
    links.forEach(link => {
      link.addEventListener('mouseenter', () => movePill(link));
      link.addEventListener('mouseleave', () => {
        const still = nav.querySelector('.active, [aria-current]');
        if (still) movePill(still); else pill.style.opacity = '0';
      });
      link.addEventListener('click', () => {
        links.forEach(l => l.classList.remove('active'));
        link.classList.add('active');
        movePill(link);
      });
    });
  });
}

/* ── Page transition overlay ───────────────────────────────── */
function initPageTransitions() {
  if (prefersReduced) return;
  const overlay = document.getElementById('mp-transition');
  if (!overlay) return;

  // Intercept local link clicks — overlay only on outgoing navigation
  document.addEventListener('click', e => {
    const link = e.target.closest('a[href]');
    if (!link) return;
    const href = link.getAttribute('href');
    if (!href || href.startsWith('#') || href.startsWith('mailto:') || href.startsWith('http') || link.target === '_blank') return;
    e.preventDefault();
    overlay.classList.add('slide-in');
    setTimeout(() => { window.location.href = href; }, 420);
  });
}

/* ── Hamburger ─────────────────────────────────────────────── */
function initHamburger() {
  document.querySelectorAll('.mp-hamburger').forEach(btn => {
    btn.addEventListener('click', () => btn.classList.toggle('open'));
  });
}

/* ── Skeleton helper ───────────────────────────────────────── */
window.MetisSkeleton = {
  show(container) {
    const c = typeof container === 'string' ? document.querySelector(container) : container;
    if (!c) return;
    c.querySelectorAll('.mp-content-fade').forEach(el => el.classList.remove('loaded'));
    c.querySelectorAll('.skeleton').forEach(el => el.style.display = '');
  },
  hide(container, delay = 400) {
    const c = typeof container === 'string' ? document.querySelector(container) : container;
    if (!c) return;
    setTimeout(() => {
      c.querySelectorAll('.skeleton').forEach(el => el.style.display = 'none');
      c.querySelectorAll('.mp-content-fade').forEach(el => el.classList.add('loaded'));
    }, delay);
  }
};

/* ── Toast API ─────────────────────────────────────────────── */
const ICONS = {
  success: '<polyline points="20 6 9 17 4 12"/>',
  error:   '<circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/>',
  warning: '<path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
  info:    '<circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/>'
};

window.toast = function(type = 'info', title = '', msg = '', duration = 4000) {
  const container = document.getElementById('mp-toasts');
  if (!container) return;
  const el = document.createElement('div');
  el.className = `mp-toast ${type}`;
  el.innerHTML = `
    <div class="mp-toast-icon">
      <svg viewBox="0 0 24 24">${ICONS[type] || ICONS.info}</svg>
    </div>
    <div class="mp-toast-body">
      ${title ? `<div class="mp-toast-title">${title}</div>` : ''}
      ${msg   ? `<div class="mp-toast-msg">${msg}</div>`   : ''}
    </div>
    <div class="mp-toast-close" title="Dismiss">×</div>
    <div class="mp-toast-progress" style="animation-duration:${duration}ms"></div>
  `;
  container.appendChild(el);
  const dismiss = () => {
    el.classList.add('dismiss');
    el.addEventListener('animationend', () => el.remove(), { once: true });
  };
  el.querySelector('.mp-toast-close').addEventListener('click', dismiss);
  el.addEventListener('click', dismiss);
  if (duration > 0) setTimeout(dismiss, duration);
  return dismiss;
};

/* ── Expose public API ─────────────────────────────────────── */
window.MetisPolish = { toast: window.toast, form: window.MetisForm, skeleton: window.MetisSkeleton };

})();
