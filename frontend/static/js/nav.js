/**
 * Shared sidebar nav for Metis shell pages.
 * Renders the same navigation block in each page's <aside class="side">.
 *
 * Usage in HTML:
 *   <aside class="side">
 *     <div class="side-head"> ... wordmark ... </div>
 *     <nav class="nav" data-active="chat|automations|manager|code|plugins"></nav>
 *     <div class="side-foot"> ... user info ... </div>
 *   </aside>
 *   <script type="module" src="/static/js/nav.js?v=v19"></script>
 */

import { ensureAuthed, getUser, clearSession, api } from '/static/js/api.js?v=v19';

const ICONS = {
  chat: '<svg class="ico" viewBox="0 0 24 24"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>',
  automations: '<svg class="ico" viewBox="0 0 24 24"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>',
  inbox: '<svg class="ico" viewBox="0 0 24 24"><path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/></svg>',
  plus: '<svg class="ico" viewBox="0 0 24 24"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>',
  recent: '<svg class="ico" viewBox="0 0 24 24"><path d="M3 3v5h5"/><path d="M3.05 13A9 9 0 1 0 5.64 5.64L3 8"/><polyline points="12 7 12 12 15 15"/></svg>',
  money: '<svg class="ico" viewBox="0 0 24 24"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>',
  manager: '<svg class="ico" viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>',
  code: '<svg class="ico" viewBox="0 0 24 24"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>',
  files: '<svg class="ico" viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>',
  plugins: '<svg class="ico" viewBox="0 0 24 24"><path d="M14.5 4h-5L7 7H4v5l3 2.5v5h5l2.5-3H20v-5L17 9V4h-2.5z"/></svg>',
};

const NAV_GROUPS = [
  {
    id: 'chat',
    label: 'Chat',
    items: [
      { id: 'chat', href: '/app', label: 'All chats', icon: ICONS.chat },
      { id: 'new-chat', href: '/app?new=1', label: 'New chat', icon: ICONS.plus },
      { id: 'recent-chats', href: '/app#recent', label: 'Recent chats', icon: ICONS.recent },
    ],
  },
  {
    id: 'work',
    label: 'Work',
    items: [
      { id: 'automations', href: '/automations', label: 'Automations', icon: ICONS.automations },
      { id: 'automation-inbox', href: '/automation-inbox', label: 'Automation Inbox', icon: ICONS.inbox },
      { id: 'money', href: '/money', label: 'Money', icon: ICONS.money },
      { id: 'manager', href: '/manager', label: 'Manager', icon: ICONS.manager },
    ],
  },
  {
    id: 'code',
    label: 'Code',
    items: [
      { id: 'code', href: '/code', label: 'Coding chats', icon: ICONS.code },
      { id: 'generated-files', href: '/code#artifacts', label: 'Generated files', icon: ICONS.files },
      { id: 'plugins', href: '/plugins', label: 'Plugin Store', icon: ICONS.plugins },
    ],
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
    navEl.innerHTML = NAV_GROUPS.map(group => {
      const groupActive = group.items.some(item => item.id === active);
      const items = group.items.map(item => `
        <a class="nav-item ${item.id === active ? 'active' : ''}" href="${item.href}">
          ${item.icon}
          <span class="lbl">${item.label}</span>
        </a>
      `).join('');
      return `
        <details class="nav-group" ${groupActive || group.id === 'chat' ? 'open' : ''}>
          <summary class="nav-heading">${group.label}</summary>
          <div class="nav-items">${items}</div>
        </details>
      `;
    }).join('');
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
