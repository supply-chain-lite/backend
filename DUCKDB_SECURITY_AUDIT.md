# DuckDB security audit

Date: 2026-09-14  
Engine reviewed: DuckDB 1.5.5 (`pyproject.toml`)  
Scope: DuckDB connection setup, SQL-client execution, environment-based remote path allowlisting, and direct maintenance connections.

## Executive result

The current connection policy successfully blocks ordinary user file access outside DuckDB's own temporary directory and permits configured remote prefixes. It also disables external access after trusted initialization, disables extension autoload/install, disables persistent secrets, and locks configuration.

There is one critical application-level regression: the SQL client currently passes the result of `query_requires_write_access()` directly as `db_access`. Recognized DuckDB writes therefore receive a writable connection and execute successfully. The SQL client does not currently enforce the requirement that DuckDB writes be rejected.

The policy is defense in depth only. DuckDB itself warns that SQL runs with the process user's privileges and should be sandboxed when input is not fully trusted.

## Findings

| Severity | Finding | Evidence and impact |
| --- | --- | --- |
| **Critical** | SQL-client catalog writes are enabled | [`execute_sql_query`](C:/Users/akhil/code/AK/supply-chain-lite/backend/app/routers/sql_client/methods.py:50) computes `write_mode` and opens `sql_connection(..., db_access=write_mode)` without rejecting DuckDB writes. `CREATE TABLE` and `INSERT` were verified to succeed through a `db_access=1` connection. An admin/owner using the SQL client can modify data and schema. |
| **High** | The local filesystem boundary includes DuckDB's temporary directory | DuckDB automatically adds `<database>.tmp/` to `allowed_directories`. A marker file placed there was readable with `read_text`, while a sibling file outside it was denied. Temporary files, spill data, or other sensitive material in that directory may therefore be exposed to SQL users. |
| **High** | Direct maintenance connections bypass the hardened policy | [`create_database`](C:/Users/akhil/code/AK/supply-chain-lite/backend/app/connections/connection.py:185), [`vacuum_model`](C:/Users/akhil/code/AK/supply-chain-lite/backend/app/connections/connection.py:199), and [`copy_database`](C:/Users/akhil/code/AK/supply-chain-lite/backend/app/connections/connection.py:213) call `duckdb.connect()` directly. This is a policy gap if a database, template, or path becomes attacker-controlled. |
| **Medium** | Extension trust is implicit rather than explicit | The wrapper preloads `httpfs`, but does not explicitly disable community or unsigned extensions. Automatic loading and installation are disabled after initialization and configuration is locked, which reduces the risk. The extension directory must still be writable only by the trusted deployment identity. |
| **Medium** | Configuration initialization has a concurrency race | Two connections can observe an unlocked configuration at the same time. One may lock it while the other is applying `SET allowed_directories`, causing that second connection to fail. The current code handles connections that see the lock before setup, but not this check-then-set race. |
| **Medium** | Untrusted workloads have no complete resource boundary | The SQL client limits returned rows to 5,000, but there is no execution deadline, memory quota, CPU quota, disk quota, or network egress limit in the reviewed code. Expensive joins, remote scans, and repeated requests can still exhaust application resources. |
| **Low/Medium** | Query text and engine errors can expose sensitive details | Failed statements are logged with the full SQL text in [`this_cursor.execute`](C:/Users/akhil/code/AK/supply-chain-lite/backend/app/connections/connection_duckdb.py:121), and raw DuckDB errors are returned in HTTP error details. SQL containing credentials, internal paths, or private URLs may be disclosed to logs or clients. |

## Current controls that are working

- `LOAD httpfs` occurs before external restrictions are applied.
- `DUCKDB_ALLOWED_DIRECTORIES` is parsed as a comma-separated list and rendered as a safely escaped DuckDB list literal.
- `enable_external_access` is set to `false` after the configured prefixes are applied.
- `autoinstall_known_extensions` and `autoload_known_extensions` are disabled.
- Persistent secrets are disabled and configuration is locked.
- `ATTACH` and `DETACH` are rejected by the cursor wrapper.
- Local paths outside DuckDB's temporary directory were denied in testing.
- A remote HTTP query under a configured prefix succeeded in an isolated test.

The allowlist approach is necessary because DuckDB 1.5.5 has a known interaction where disabling `LocalFileSystem` prevents `httpfs` remote access. See [DuckDB issue #15734](https://github.com/duckdb/duckdb/issues/15734). DuckDB's security documentation also states that settings are defense in depth and not a substitute for process or container sandboxing: [Securing DuckDB](https://duckdb.org/docs/current/operations_manual/securing_duckdb/overview).

## SQL-client statement coverage

`query_requires_write_access()` recognizes ordinary catalog writes such as `CREATE`, `INSERT`, `UPDATE`, `DELETE`, `ALTER`, `DROP`, `MERGE`, and `VACUUM`, but the SQL-client route does not reject them. This is the critical issue above.

It does not classify several side-effecting statements, including `EXPORT DATABASE`, `COPY ... TO`, `LOAD`, `INSTALL`, `SET`, and `CHECKPOINT`. In the current hardened connection these are generally stopped by `enable_external_access=false` or `lock_configuration`, but relying on the classifier remains unsafe. The SQL client should use an allowlist of permitted read statement types instead of choosing a writable connection from a write detector.

## Required remediation

1. Reject every DuckDB statement requiring write access in the SQL-client route, or make every SQL-client DuckDB connection `db_access=0` unconditionally.
2. Apply the same hardened connection helper to database creation, checkpointing, and backup preparation, or keep those operations in a separate trusted process with tightly controlled inputs.
3. Treat the automatically allowed `<database>.tmp/` directory as sensitive. Use a private per-model temporary directory containing no application secrets, and run the worker under an OS identity that cannot read other models or credentials.
4. Set `allow_community_extensions=false` and `allow_unsigned_extensions=false` during trusted initialization, and verify extension files are owned and writable only by deployment administrators.
5. Handle the configuration race with a process-level initialization lock or a retry that verifies the resulting settings before continuing.
6. Add application-level timeouts, memory/CPU/disk limits, and outbound network controls. Run untrusted SQL in a restricted worker or container.
7. Redact SQL text and filesystem/URL details from logs and API errors where they may contain secrets.

## Verification performed

- `python -m unittest tests.test_connections`: 19 tests passed.
- Ruff checks passed for the DuckDB connection and connection tests.
- Verified `CREATE TABLE` and `INSERT` succeed on the current writable DuckDB path, confirming the SQL-client write-control regression.
- Verified local access outside the DuckDB temporary directory is denied.
- Verified a file in the automatically allowed DuckDB temporary directory is readable.
- Verified a configured remote HTTP prefix can be queried through the current connection policy.
