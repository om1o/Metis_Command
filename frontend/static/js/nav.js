/**
 * Shared sidebar nav for Money / People / Automations / Chat pages.
 * Renders the same navigation block in each page's <aside class="side">.
 *
 * Usage in HTML:
 *   <aside class="side">
 *     <div class="side-head"> ... wordmark ... </div>
 *     <nav class="nav" data-active="money|people|automations|chat"></nav>
 *     <div class="side-foot"> ... user info ... </div>
 *   </aside>
 *   <script type="module" src="/static/js/nav.js?v=v17"></script>
 */

import { ensureAuthed, getUser, clearSession, api } from '/static/js/api.js?v=v17';

const NAV_ITEMS = [
  {
    id: 'chat',
    href: '/app',
    label: 'Chat',
    svg: '<svg class="ico" viewBox="0 0 24 24"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>',
  },
  {
    id: 'money',
    href: '/money',
    label: 'Money',
    svg: '<svg class="ico" viewBox="0 0 24 24"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>',
  },
  {
    id: 'people',
    href: '/people',
    label: 'Relationships',
    svg: '<svg class="ico" viewBox="0 0 24 24"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>',
  },
  {
    id: 'automations',
    href: '/automations',
    label: 'Automations',
    svg: '<svg class="ico" viewBox="0 0 24 24"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>',
  },
  {
    id: 'inspector',
    href: '/inspector',
    label: 'Subagents',
    svg: '<svg class="ico" viewBox="0 0 24 24"><circle cx="6" cy="6" r="3"/><circle cx="18" cy="6" r="3"/><circle cx="12" cy="18" r="3"/><line x1="9" y1="7" x2="15" y2="7"/><line x1="8" y1="9" x2="11" y2="15"/><line x1="16" y1="9" x2="13" y2="15"/></svg>',
  },
  {
    id: 'browser',
    href: '/browser-control',
    label: 'Browser',
    svg: '<svg class="ico" viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><circle cx="6" cy="6" r=".5" fill="currentColor"/><circle cx="9" cy="6" r=".5" fill="currentColor"/></svg>',
  },
];

export async function mountNav() {
  const user = await ensureAuthed();
  if (!user) return;
  const cached = getUser() || user;
  const email = cached.email || 'Operator';

  const navEl = document.querySelector('.nav');
  if (navEl) {
    const active = navEl.dataset.active || '';
    navEl.innerHTML = NAV_ITEMS.map(item => `
      <a class="nav-item ${item.id === active ? 'active' : ''}" href="${item.href}">
        ${item.svg}
        <span class="lbl">${item.label}</span>
      </a>
    `).join('');
  }

  const userName = document.getElementById('userName');
  const userAvatar = document.getElementById('userAvatar');
  if (userName) userName.textContent = email;
  if (userAvatar) userAvatar.textContent = (email[0] || 'M').toUpperCase();

  // Sign-out button if present
  const signoutBtn = document.getElementById('signoutBtn');
  if (signoutBtn) {
    signoutBtn.addEventListener('click', async () => {
      try { await api.signout(); } catch {}
      clearSession();
      window.location.replace('/login');
    });
  }
}

mountNav();
