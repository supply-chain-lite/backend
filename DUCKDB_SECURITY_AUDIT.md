# DuckDB security audit

Updated: 2026-09-15
Engine reviewed: DuckDB 1.5.5 (`pyproject.toml`)
Scope: Current DuckDB connection setup, SQL-client execution, remote path allowlisting, S3 credentials, and direct maintenance connections.

## Executive result

Model connections disable external access after trusted initialization, disable automatic extension installation/loading, and disable persistent secrets. Configured prefixes are passed to `allowed_directories`. The wrapper rejects `ATTACH`, `DETACH`, and multiple statements in one `execute()` call.

The previous SQL-client write regression is resolved: recognized DuckDB writes receive HTTP 403, and every remaining DuckDB SQL-client query opens a native read-only connection. Other application callers can explicitly request writable connections.

S3 credential discovery is now opt-in. With neither a complete pair of S3 keys nor `DUCKDB_S3_CREDENTIAL_CHAIN` enabled, setup skips secret creation and loading `aws`. This avoids repeated unsuccessful credential discovery on local machines.

The implementation does **not** set `lock_configuration=true`. Disabling external access must not be described as a blanket lock on all settings. These controls do not provide process isolation or a complete resource boundary.

## Current connection lifecycle

Source: [connection_duckdb.py](app/connections/connection_duckdb.py).

Each context opens a fresh connection to an existing database file. DuckDB connections are not retained in the application's SQLite connection pool. `sql_connection` defaults DuckDB access to `db_access=0` (read-only); `db_access=1` opens the file writable.

Initialization runs in this order:

1. Check that the context is not already open and the database file exists, then call `duckdb.connect()` with the selected access mode.
2. Execute `LOAD <extension>;` for each unique, nonempty extension in `DUCKDB_EXTENSIONS`.
   The default is `httpfs`; the repository `.env` sets `httpfs,aws,json,excel`.
3. Apply the following settings, in order:

   ```sql
   SET allowed_directories = <escaped list from DUCKDB_ALLOWED_DIRECTORIES>;
   SET autoinstall_known_extensions = false;
   SET autoload_known_extensions = false;
   SET allow_persistent_secrets = false;
   ```

4. Configure the optional, non-persistent `model_s3` secret as described below.
5. Apply `SET enable_external_access = false`.
6. Use the same native connection for execution and transactions, execute `BEGIN`, and return the cursor wrapper.

Secret-manager settings precede secret creation, and secret creation precedes disabling external access. `DUCKDB_ALLOWED_DIRECTORIES` is split on commas, trimmed, and SQL-escaped; an unset value produces `[]`. The code does not validate that entries are remote URLs, so configured local paths would also be passed through.

`_apply_settings()` catches `duckdb.InvalidInputException`. It re-raises if `enable_external_access` is still true; otherwise it suppresses the exception to tolerate settings already restricted by another connection to the shared database instance. It does not verify every requested setting, and an exception skips the remaining statements in that invocation. There is no application-level initialization lock in this implementation.

On normal context exit, the transaction commits. A body exception or failed commit triggers a rollback attempt, and exit always closes the connection. Failed `BEGIN` also closes it. Earlier initialization steps are outside that cleanup handler; see the remaining findings.

## S3 credentials and extension setup

| Configuration | Connection behavior |
| --- | --- |
| Both `S3_ACCESS_KEY` and `S3_SECRET_KEY` are nonempty | Create `model_s3` with explicit `KEY_ID` and `SECRET`. Skip `LOAD aws`; explicit keys take precedence over credential-chain opt-in. |
| Keys are incomplete or absent, and `DUCKDB_S3_CREDENTIAL_CHAIN` is enabled | Attempt `LOAD aws`, then create `model_s3` with `PROVIDER credential_chain` and `REFRESH auto`. |
| Keys are incomplete or absent, and discovery is disabled | Return from secret setup without executing secret SQL or loading `aws`. Remote requests have no application-configured S3 signing secret. |

`DUCKDB_S3_CREDENTIAL_CHAIN` defaults to `false`. After trimming whitespace and lowercasing, `1`, `true`, `yes`, and `on` enable it. AWS environment variables, a region, an endpoint, or a profile alone do not opt in to discovery.

`DUCKDB_EXTENSIONS` is parsed as a comma-separated list, with whitespace removed,
names lowercased, and duplicates removed while preserving order. It defaults to
`httpfs`; an empty value is rejected. `install_duckdb_extensions()` installs exactly
that list from the `core` repository, and each model connection loads exactly that list.
If credential-chain S3 access is enabled while `aws` is absent from the configured list,
the connection makes an additional best-effort `LOAD aws` before creating the secret.

Additional secret fields:

- Region comes from the first nonempty value of `S3_REGION`, `AWS_REGION`, or `AWS_DEFAULT_REGION`.
- When `S3_URL` is set, the code splits it at `://`, uses the remainder as `ENDPOINT`, selects path-style URLs, and disables SSL only for the exact `http` scheme. The endpoint should therefore include its scheme.
- String values are escaped before insertion into SQL.
- No `SCOPE` field is set. Credential scope is not narrowed to a particular model or bucket by this code; the configured path allowlist is a separate control.

The code uses `CREATE OR REPLACE SECRET`, without `PERSISTENT`, and disables persistent secrets beforehand. Secret setup is attempted on every new context when configured; there is no application credential cache or one-time initialization flag. Opting in to the credential chain therefore retains discovery work on new connections. Skipping unconfigured S3 setup does not remove `LOAD httpfs` or other initialization work.

An unavailable `aws` extension produces a warning, after which secret creation is still attempted. A DuckDB error during secret creation is logged and does not stop connection setup. On a fresh database instance, failed creation leaves remote reads unsigned; authenticated S3 access can consequently fail while local queries remain usable. When database state is shared with another open connection, this handler does not inspect whether an existing secret remains available.

[install_duckdb_extensions()](app/database.py) installs exactly the comma-separated `DUCKDB_EXTENSIONS` list from the `core` repository during API database initialization, reusing existing installations. The default is `httpfs`; the repository `.env` configures `httpfs,aws,json,excel`. Installation failure raises an explanatory error and stops initialization. Per-connection loading follows the same list, with a best-effort additional `aws` load only when credential-chain S3 access is enabled and `aws` was omitted from the list.

## SQL-client statement controls

Sources: [SQL-client methods](app/routers/sql_client/methods.py) and [connection routing](app/connections/connection.py).

- SQL-client execution requires model access level `admin` or `owner`.
- `query_requires_write_access()` recognizes ordinary catalog writes, including `CREATE`, `INSERT`, `UPDATE`, `DELETE`, `ALTER`, `DROP`, `MERGE`, and `VACUUM`. It also examines statements wrapped by `EXPLAIN`, including `ANALYZE` and parenthesized options.
- The route rejects classified DuckDB writes with HTTP 403 before opening a model connection, and explicitly forces `db_access=0` for all remaining DuckDB queries.
- The cursor wrapper parses statements and rejects `ATTACH` and `DETACH`. `execute()` requires exactly one statement. The separate `executescript()` helper validates all script statements before executing them individually; the SQL-client route uses `execute()`.
- `get_description()` obtains SELECT metadata through a relation. For other statements, it uses `EXPLAIN` unless the statement is already an `EXPLAIN`; it does not execute a write merely to determine result columns. Metadata binding can still access external sources permitted by the connection policy.
- Results are limited to 5,000 fetched rows. This is a response-size limit, not a limit on query execution cost.

The write classifier is not a general statement allowlist. For example, it does not classify `EXPORT DATABASE`, `COPY ... TO`, `LOAD`, `INSTALL`, `SET`, or `CHECKPOINT` as ordinary catalog writes. Native read-only mode protects database writes, while external-access and extension settings provide separate restrictions. The wrapper does not categorically reject all settings or all statements with external side effects, and there is no blanket `lock_configuration` control.

## Findings and status

| Status / severity | Finding | Evidence and impact |
| --- | --- | --- |
| **Resolved** | SQL-client catalog writes previously received writable connections | The route now rejects recognized DuckDB writes and forces all remaining DuckDB SQL-client connections to read-only. Writable connections remain available to other application workflows. |
| **High - prior observation** | The filesystem boundary includes DuckDB's temporary directory | The 2026-09-14 audit reported that a marker under `<database>.tmp/` was readable while a sibling file was denied. This specific probe was not repeated for this update; keep temporary-directory contents within the trust boundary until revalidated. |
| **High** | Direct maintenance connections bypass the model connection policy | `create_database()`, `vacuum_model()`, and `copy_database()` call `duckdb.connect()` directly. This is a policy gap if a database, template, or path becomes attacker-controlled. |
| **Medium** | Initialization does not verify the complete shared configuration | `_apply_settings()` suppresses an `InvalidInputException` when external access is already disabled, without checking the allowlist or each extension/secret setting. It can skip remaining settings. The previous lock-check implementation has been replaced, but complete initialization under concurrency is not established. |
| **Medium** | Early initialization failures lack explicit cleanup | Extension loading, settings application, and S3 setup occur before the `try` covering `BEGIN`. A failure escaping those steps can leave an opened connection without an explicit close; `sql_connection.__enter__()` only delegates and adds no cleanup. |
| **Medium** | Extension trust restrictions are not all explicit | Startup installation names the `core` repository and setup disables automatic installation/loading. The configured `DUCKDB_EXTENSIONS` list is operator-controlled, and the wrapper does not explicitly set `allow_community_extensions=false` or `allow_unsigned_extensions=false`; extension-file permissions remain part of deployment trust. |
| **Medium** | S3 credentials are not scoped per model or bucket | Connections use the same environment-supplied credentials, and secret SQL has no `SCOPE`. Review remote prefixes and credential permissions together. |
| **Medium** | Untrusted workloads have no complete resource boundary | The reviewed connection and SQL-client code sets no execution deadline or explicit memory, CPU, disk, or network egress quota. Expensive queries can exhaust resources despite the returned-row limit. |
| **Low/Medium** | Query text and engine errors can expose sensitive details | Failed SQL is logged in full, secret-creation failures include exception details, and raw engine errors are returned in SQL-client HTTP errors. SQL containing credentials, internal paths, or private URLs may reach logs or clients. |

## Remaining remediation

1. Keep database creation, checkpointing, and backup inputs trusted, or route them through a policy appropriate to those operations.
2. Revalidate temporary-directory access on the deployed DuckDB build and keep application secrets out of allowed paths and spill directories.
3. Validate allowed prefixes and S3 endpoint configuration, and scope credentials to required data. Review whether secrets also need an explicit `SCOPE`.
4. Verify the complete effective policy when initialization encounters shared settings, and close the native connection on every initialization failure.
5. Explicitly configure extension trust settings where required and restrict write access to installed extension files.
6. Add query resource limits and process/network isolation appropriate to the trust level of SQL users.
7. Redact sensitive SQL and engine details from logs and API responses.

## Verification and limits

Verification available from the 2026-09-15 connection implementation update:

- `python -m unittest discover -s tests -p test_connections.py`: 22 tests passed.
- Ruff checks passed for `connection_duckdb.py` and `tests/test_connections.py`.
- Existing integration tests cover native read-only behavior, transaction cleanup, separate overlapping reader connections, local CSV denial, statement restrictions, and metadata handling.
- Four added connection tests use mocked connections to check repeated unconfigured setup skips secret SQL and unnecessary `LOAD aws`, explicit keys take precedence without AWS discovery, credential-chain opt-in preserves setup order and `REFRESH auto`, and configured extensions load once in order.

This document update was checked against the current source. SQL-client route behavior was reviewed in code; the connection suite does not constitute an end-to-end HTTP authorization test. The S3 setup tests do not exercise live credentials, refresh, or authenticated remote access.

The earlier audit also reported successful reads from a configured remote HTTP prefix and from DuckDB's temporary directory. Those are historical observations, not fresh verification of the current implementation. No new remote-access, concurrency stress, resource-exhaustion, or complete sandbox audit was performed for this documentation update.
