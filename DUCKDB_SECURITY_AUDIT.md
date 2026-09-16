# DuckDB security audit

Updated: 2026-09-16
Engine reviewed: DuckDB 1.5.5 (`pyproject.toml`)
Scope: Current DuckDB connection setup, database-file upload/download behavior, SQL-client execution, remote path allowlisting, S3 credentials, and direct maintenance connections.

## Executive result

Model connections disable external access after trusted initialization, disable automatic extension installation/loading, and disable persistent secrets. Configured prefixes are passed to `allowed_directories`. The wrapper rejects `ATTACH`, `DETACH`, and multiple statements in one `execute()` call.

The previous SQL-client write regression is resolved: recognized DuckDB writes receive HTTP 403, and every remaining DuckDB SQL-client query opens a native read-only connection. Other application callers can explicitly request writable connections.

S3 credential discovery is now opt-in. With neither a complete pair of S3 keys nor `DUCKDB_S3_CREDENTIAL_CHAIN` enabled, setup skips secret creation and loading `aws`. This avoids repeated unsuccessful credential discovery on local machines.

DuckDB configuration values such as `enable_external_access` and `allowed_directories` are global to the live database instance, but are not serialized into the `.duckdb` file. A database edited offline with external access enabled therefore reopens with the normal defaults, and each application connection reapplies the service policy before serving queries. Uploads can still preserve catalog objects such as views and macros, so the file itself must be treated as untrusted input.

DuckDB connections now apply resource limits at startup: `DUCKDB_MEMORY_LIMIT` defaults to `1GB`, `DUCKDB_THREADS` to `2`, and `DUCKDB_MAX_TEMP_DIRECTORY_SIZE` to `2GB`. Each wrapped DuckDB operation, including result fetching, has a `DUCKDB_QUERY_TIMEOUT_SECONDS` limit that defaults to `60` seconds and interrupts the connection when exceeded. The same limits and timeout apply to direct database creation, copy, and maintenance operations. These are defense-in-depth controls, not process-level CPU quotas or a substitute for isolation.

The implementation does **not** set `lock_configuration=true`. Disabling external access must not be described as a blanket lock on all settings. These controls do not provide process isolation or a complete resource boundary.

## Current connection lifecycle

Source: [connection_duckdb.py](app/connections/connection_duckdb.py).

Each context opens a fresh connection to an existing database file. DuckDB connections are not retained in the application's SQLite connection pool. `sql_connection` defaults DuckDB access to `db_access=0` (read-only); `db_access=1` opens the file writable.

Initialization runs in this order:

1. Check that the context is not already open and the database file exists, then call `duckdb.connect()` with the selected access mode.
2. Apply `SET allow_persistent_secrets = false;` before any secret-manager use.
3. Execute `LOAD <extension>;` for each unique, nonempty extension in `DUCKDB_EXTENSIONS`.
   The default is `httpfs`; the repository `.env` sets `httpfs,aws,json,excel`.
4. Apply the following remaining settings, in order:

   ```sql
   SET allowed_directories = <escaped list from DUCKDB_ALLOWED_DIRECTORIES>;
   SET autoinstall_known_extensions = false;
   SET autoload_known_extensions = false;
   ```

Resource limits are supplied as connection-start configuration before these settings are applied. Direct database creation, copy, and maintenance connections use the same resource configuration and timeout wrapper.

5. Configure the optional, non-persistent `model_s3` secret as described below.
6. Apply `SET enable_external_access = false`.
7. Use the same native connection for execution and transactions, execute `BEGIN`, and return the cursor wrapper.

Secret-manager settings precede secret creation, and secret creation precedes disabling external access. `DUCKDB_ALLOWED_DIRECTORIES` is split on commas, trimmed, and SQL-escaped; an unset value produces `[]`. The code does not validate that entries are remote URLs, so configured local paths would also be passed through.

`_apply_settings()` catches `duckdb.InvalidInputException` per statement. It re-raises while `enable_external_access` is still true, and otherwise tolerates the error as shared state already restricted by another connection. For `allow_persistent_secrets`, it additionally checks that the setting is already false. Other settings are not individually verified when external access is already disabled, so complete effective-policy verification under concurrency is not established. There is no application-level initialization lock in this implementation.

On normal context exit, the transaction commits. A body exception or failed commit triggers a rollback attempt, and exit always closes the connection. Failed initialization, including extension loading, settings, secret setup, and `BEGIN`, also closes the connection.

## Database-file upload and download behavior

Sources: [model methods](app/routers/models/methods.py) and [connection lifecycle helpers](app/connections/connection.py).

- Downloads create a temporary destination and call `copy_database()` before returning the file.
- Uploads require `owner` or `editor` access, reject an active model task, write the multipart body to a temporary file, and identify the engine from the file signature rather than the filename.
- DuckDB uploads are then opened with plain `duckdb.connect()`, checkpointed, closed, and copied byte-for-byte to the live model path. The `restore` flag does not create a sanitized or reconstructed database for DuckDB.
- The upload path does not inspect or remove stored views, macros, persistent-secret metadata, extension references, or other catalog objects.

An offline `SET enable_external_access = true` is not a persistent bypass: after the creating connection closes, the setting is not retained in the database file, and the next application connection applies `enable_external_access = false`. However, opening and checkpointing an untrusted DuckDB file in the application process remains a parser and resource-exhaustion trust boundary. A crafted catalog object can also cause external access to an allowlisted URL when the application later queries it; access outside the configured policy should remain blocked by the hardened model connection.

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
| **High when uploads are untrusted** | Uploaded DuckDB files are parsed and checkpointed through an unrestricted connection | `upload_model()` checks only the file signature before `copy_database()` opens the source with default DuckDB settings and executes `CHECKPOINT`; the resulting file is copied byte-for-byte. This is not evidence that `enable_external_access` persists, but it exposes the main process to malformed/pathological database files and preserves attacker-controlled catalog objects. |
| **High** | Direct maintenance connections bypass the model connection policy | `create_database()`, `vacuum_model()`, and `copy_database()` call `duckdb.connect()` directly. This is a policy gap if a database, template, or path becomes attacker-controlled. |
| **Medium** | Initialization does not verify the complete shared configuration | `_apply_settings()` suppresses an `InvalidInputException` when external access is already disabled, without checking the allowlist or each extension/secret setting. It can skip remaining settings. The previous lock-check implementation has been replaced, but complete initialization under concurrency is not established. |
| **Resolved** | Initialization failures could leave native connections open | The current `duckdb_connection.__enter__()` wraps extension loading, settings, secret setup, and `BEGIN` in a cleanup handler; failures call `_close()`. |
| **Medium** | Extension trust restrictions are not all explicit | Startup installation names the `core` repository and setup disables automatic installation/loading. The configured `DUCKDB_EXTENSIONS` list is operator-controlled, and the wrapper does not explicitly set `allow_community_extensions=false` or `allow_unsigned_extensions=false`; extension-file permissions remain part of deployment trust. |
| **Medium** | S3 credentials are not scoped per model or bucket | Connections use the same environment-supplied credentials, and secret SQL has no `SCOPE`. Review remote prefixes and credential permissions together. |
| **Medium** | Stored catalog objects can trigger configured external reads | Uploaded views or macros survive the byte-for-byte copy. When later queried, they execute under the application connection; `enable_external_access=false` blocks unallowlisted sources, but `DUCKDB_ALLOWED_DIRECTORIES` intentionally permits configured URL/path prefixes. |
| **Medium** | Untrusted workloads are not fully isolated | Model connections now apply configurable memory, worker-thread, temporary-spill, and per-operation timeout limits. These do not impose a hard OS CPU quota, prevent all resource contention, or protect the process from malicious database-file/parser behavior; process/network isolation remains required for hostile input. |
| **Low/Medium** | Query text and engine errors can expose sensitive details | Failed SQL is logged in full, secret-creation failures include exception details, and raw engine errors are returned in SQL-client HTTP errors. SQL containing credentials, internal paths, or private URLs may reach logs or clients. |

## Remaining remediation

1. Validate uploaded DuckDB files with a hardened connection before replacement, or process them in a separate low-privilege process/container with no network access or application secrets. Prefer reconstructing trusted tables over accepting arbitrary catalog objects when uploads are untrusted.
2. Keep database creation, checkpointing, and backup inputs trusted, or route them through a policy appropriate to those operations.
3. Revalidate temporary-directory access on the deployed DuckDB build and keep application secrets out of allowed paths and spill directories.
4. Validate allowed prefixes and S3 endpoint configuration, and scope credentials to required data. Review whether secrets also need an explicit `SCOPE`.
5. Verify the complete effective policy when initialization encounters shared settings; consider setting `lock_configuration=true` after trusted initialization.
6. Explicitly configure extension trust settings where required and restrict write access to installed extension files.
7. Tune the DuckDB limits for deployment and add process/network isolation appropriate to the trust level of SQL users; application timeouts are not a hard CPU or memory sandbox.
8. Redact sensitive SQL and engine details from logs and API responses.

## Verification and limits

Verification available from the 2026-09-16 review:

- `python -m unittest discover -s tests -p test_connections.py`: 23 tests passed.
- Ruff checks passed for `connection_duckdb.py` and `tests/test_connections.py`.
- Existing integration tests cover native read-only behavior, transaction cleanup, separate overlapping reader connections, local CSV denial, statement restrictions, and metadata handling.
- Four added connection tests use mocked connections to check repeated unconfigured setup skips secret SQL and unnecessary `LOAD aws`, explicit keys take precedence without AWS discovery, credential-chain opt-in preserves setup order and `REFRESH auto`, and configured extensions load once in order.
- A live DuckDB 1.5.5 probe confirmed that `enable_external_access` and `allowed_directories` return to their defaults after closing and reopening the database file. The same probe confirmed that attempts to re-enable external access, change the allowlist, or change autoload settings after external access is disabled are rejected.
- Connection tests verify that resource settings are passed at startup, and a live operation test verifies that a long-running DuckDB query is interrupted and reported as a timeout.

This document update was checked against the current source. SQL-client route behavior was reviewed in code; the connection suite does not constitute an end-to-end HTTP authorization test. The S3 setup tests do not exercise live credentials, refresh, or authenticated remote access.

The earlier audit also reported successful reads from a configured remote HTTP prefix and from DuckDB's temporary directory. Those are historical observations, not fresh verification of the current implementation. No new remote-access, upload end-to-end, concurrency stress, resource-exhaustion, or complete sandbox audit was performed for this documentation update.
