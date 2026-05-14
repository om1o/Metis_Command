-- Resolve Supabase advisor warnings before memory and sync history volume grows:
-- - 0001_unindexed_foreign_keys on public.memory.user_id and public.sync_log.user_id
-- - 0003_auth_rls_initplan for auth.uid() calls in RLS policies

create index if not exists memory_user_session_created_at_idx
  on public.memory (user_id, session_id, created_at);

create index if not exists sync_log_user_created_at_idx
  on public.sync_log (user_id, created_at desc);

alter policy "Users can manage their own memory"
  on public.memory
  to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);

alter policy "Users can view their own sync log"
  on public.sync_log
  to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);
