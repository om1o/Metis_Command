from pathlib import Path


ROOT = Path.cwd()
if not (ROOT / "schema.sql").is_file():
    ROOT = Path(__file__).absolute().parents[2]
SCHEMA_SQL = ROOT / "schema.sql"
MIGRATION_SQL = next(
    (ROOT / "supabase" / "migrations").glob("*_fix_memory_sync_rls_indexes.sql")
)


def _normalise(sql: str) -> str:
    return " ".join(sql.lower().split())


def _policy_statements(sql: str, policy_name: str, table: str) -> list[str]:
    policy_marker = f'"{policy_name.lower()}"'
    table_marker = f"public.{table}"
    return [
        _normalise(statement)
        for statement in sql.split(";")
        if policy_marker in statement.lower() and table_marker in statement.lower()
    ]


def test_memory_and_sync_log_foreign_keys_have_left_anchored_indexes() -> None:
    migration_sql = _normalise(MIGRATION_SQL.read_text(encoding="utf-8"))
    schema_sql = _normalise(SCHEMA_SQL.read_text(encoding="utf-8"))

    for sql in (migration_sql, schema_sql):
        assert (
            "create index if not exists memory_user_session_created_at_idx "
            "on public.memory (user_id, session_id, created_at)"
        ) in sql
        assert (
            "create index if not exists sync_log_user_created_at_idx "
            "on public.sync_log (user_id, created_at desc)"
        ) in sql


def test_memory_and_sync_log_policies_cache_auth_uid_per_statement() -> None:
    for path in (MIGRATION_SQL, SCHEMA_SQL):
        sql = path.read_text(encoding="utf-8")

        memory_policies = _policy_statements(sql, "Users can manage their own memory", "memory")
        sync_log_policies = _policy_statements(
            sql,
            "Users can view their own sync log",
            "sync_log",
        )

        assert memory_policies
        assert sync_log_policies

        for statement in [*memory_policies, *sync_log_policies]:
            assert " to authenticated " in f" {statement} "
            assert "using ((select auth.uid()) = user_id)" in statement
            assert "with check ((select auth.uid()) = user_id)" in statement
            assert "using (auth.uid() = user_id)" not in statement
            assert "with check (auth.uid() = user_id)" not in statement
