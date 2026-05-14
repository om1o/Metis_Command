-- ============================================================
-- Metis Command — Supabase Schema (V16.3 Apex)
-- Run this once in your Supabase project's SQL Editor.
-- ============================================================

-- ── memory ────────────────────────────────────────────────────
create table if not exists public.memory (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid references auth.users(id) on delete cascade,
  session_id  text not null,
  role        text not null check (role in ('user', 'assistant', 'system')),
  content     text not null,
  created_at  timestamptz not null default now()
);

create index if not exists memory_session_idx on public.memory (session_id, created_at);
create index if not exists memory_user_session_created_at_idx
  on public.memory (user_id, session_id, created_at);

alter table public.memory enable row level security;

create policy "Users can manage their own memory"
  on public.memory
  for all
  to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);


-- ── sync_log ──────────────────────────────────────────────────
create table if not exists public.sync_log (
  id           uuid primary key default gen_random_uuid(),
  user_id      uuid references auth.users(id) on delete set null,
  local_path   text not null,
  remote_path  text not null,
  action       text not null check (action in ('upload', 'download')),
  url          text,
  created_at   timestamptz not null default now()
);

alter table public.sync_log enable row level security;

create index if not exists sync_log_user_created_at_idx
  on public.sync_log (user_id, created_at desc);

create policy "Users can view their own sync log"
  on public.sync_log
  for all
  to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);


-- ── leads (swarm mission output) ─────────────────────────────
create table if not exists public.leads (
  id           uuid primary key default gen_random_uuid(),
  topic        text not null,
  raw_output   text,
  status       text not null default 'new' check (status in ('new', 'reviewed', 'sent', 'archived')),
  created_at   timestamptz not null default now()
);

alter table public.leads enable row level security;

create policy "Service role manages leads"
  on public.leads
  for all
  using (true)
  with check (true);


-- ── identities (persona store) ────────────────────────────────
create table if not exists public.identities (
  id          uuid primary key default gen_random_uuid(),
  name        text unique not null,
  role        text not null,
  personality text not null,
  directives  text[],
  active      boolean default false,
  created_at  timestamptz default now()
);

alter table public.identities enable row level security;

create policy "Service role manages identities"
  on public.identities
  for all
  using (true)
  with check (true);


-- ── skills ────────────────────────────────────────────────────
create table if not exists public.skills (
  id          uuid primary key default gen_random_uuid(),
  name        text unique not null,
  description text,
  code        text not null,
  enabled     boolean default true,
  created_at  timestamptz default now()
);

alter table public.skills enable row level security;

create policy "Service role manages skills"
  on public.skills
  for all
  using (true)
  with check (true);


-- ── users_subscription (Free / Pro / Enterprise tiers) ───────
create table if not exists public.users_subscription (
  user_id              uuid primary key references auth.users(id) on delete cascade,
  tier                 text not null default 'Free' check (tier in ('Free', 'Pro', 'Enterprise')),
  stripe_customer_id   text,
  stripe_subscription  text,
  current_period_end   timestamptz,
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now()
);

alter table public.users_subscription enable row level security;

create policy "Users read their own subscription"
  on public.users_subscription
  for select
  using (auth.uid() = user_id);

create policy "Service role manages subscriptions"
  on public.users_subscription
  for all
  using (true)
  with check (true);


-- ── plugins_store (marketplace catalog) ──────────────────────
create table if not exists public.plugins_store (
  slug           text primary key,
  name           text not null,
  description    text,
  price_cents    integer not null default 0,
  tier_required  text not null default 'Free' check (tier_required in ('Free', 'Pro', 'Enterprise')),
  icon           text,
  download_url   text,
  enabled        boolean default true,
  created_at     timestamptz not null default now()
);

alter table public.plugins_store enable row level security;

create policy "Anyone can read the plugin catalog"
  on public.plugins_store
  for select
  using (true);

create policy "Service role manages plugin catalog"
  on public.plugins_store
  for all
  using (true)
  with check (true);


-- ── purchases (plugin-level purchases) ───────────────────────
create table if not exists public.purchases (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid references auth.users(id) on delete cascade,
  plugin_slug   text not null references public.plugins_store(slug),
  stripe_session text,
  status        text not null default 'pending' check (status in ('pending','paid','refunded','failed')),
  created_at    timestamptz not null default now()
);

alter table public.purchases enable row level security;

create policy "Users manage their own purchases"
  on public.purchases
  for all
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);


-- ── Seed 5 launch plugins ────────────────────────────────────
insert into public.plugins_store (slug, name, description, price_cents, tier_required, icon)
values
  ('stock_terminal',     'Stock Terminal',       'Live market quotes via Yahoo Finance.',        0,   'Free', '📈'),
  ('stealth_scraper',    'Stealth Web Scraper',  'Playwright-based headless browser scraping.', 0,   'Pro',  '🕵️'),
  ('discord_automator',  'Discord Automator',    'Post, edit, and schedule Discord messages.',  999, 'Free', '💬'),
  ('crypto_analyst',     'Crypto Analyst',       'CoinGecko prices + simple sentiment take.',   0,   'Free', '🪙'),
  ('spotify_controller', 'Spotify Controller',   'Play, pause, queue, and search Spotify.',     499, 'Free', '🎵')
on conflict (slug) do nothing;


-- ── Storage bucket ────────────────────────────────────────────
insert into storage.buckets (id, name, public)
values ('metis-artifacts', 'metis-artifacts', true)
on conflict (id) do nothing;

create policy "Authenticated uploads"
  on storage.objects
  for insert
  to authenticated
  with check (bucket_id = 'metis-artifacts');

create policy "Public read access"
  on storage.objects
  for select
  to public
  using (bucket_id = 'metis-artifacts');
