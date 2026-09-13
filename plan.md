# SQLite and DuckDB follow-up plan

This plan covers the work remaining after introducing database-specific connection adapters. It records implementation work to do; it does not mean that all model features already support DuckDB.

## Requirements to preserve

- Keep `app/connections/connection.py` as the application entry point.
- The master database always uses SQLite. Only non-master model databases may use DuckDB.
- Preserve existing SQLite behavior, including connection pooling and existing SQLite models without `db_type` metadata.
- SQLite connections always open read-write and pool by database path and thread. The SQLite adapter does not accept or enforce `db_access`; the shared entry point ignores it for SQLite. Transactions still begin with deferred `BEGIN`.
- Never pool DuckDB connections. Each connection context opens a fresh connection and closes it on success or failure.
- Database writes and schema changes must explicitly use `db_access=1`. DuckDB reads default to `db_access=0`.
- Preserve ownership, sharing permissions, running-task restrictions, and model identity checks throughout lifecycle operations.
- Preserve the source engine during copy, backup, restore, download, and task execution. Cross-engine conversion is a separate feature.

## Current status

- [x] Introduce SQLite and DuckDB adapters behind `connection.py`.
- [x] Keep master connections on SQLite with write access.
- [x] Add connection tests for pooling, connection closure, transactions, metadata, and the SQL client's description/execution sequence.
- [x] Declare `duckdb==1.5.5` in `pyproject.toml` (present when this plan was written).
- [ ] Synchronize `uv.lock`; it currently has no DuckDB entry. Verify a clean environment can install and run the backend and workers.

## 1. Engine metadata and shared lifecycle operations

- [ ] Define the source of `db_type` for new models and templates. Keep missing legacy metadata equivalent to SQLite.
- [ ] Persist `db_type` in model metadata when creating or copying models. `app/routers/models/queries.py::insert_models` currently does not write it.
- [ ] Carry engine information through backup records or a reliably validated association with the source model, task records, scheduler queries, and worker payloads.
- [ ] Stop choosing a driver from a filename suffix alone. Preserve existing SQLite paths while defining extensions for newly created DuckDB models and artifacts.
- [ ] Add reusable engine-specific lifecycle helpers for creation, consistent snapshots, restore/replacement, maintenance, and deletion. Ordinary cursor operations alone do not cover whole-file lifecycle work.
- [ ] Give helpers that mutate databases an explicit write-access contract. Operations such as checkpointing or vacuum may require a dedicated connection outside the normal request transaction.
- [ ] Define how active requests are excluded during replacement, deletion, and maintenance. Account for API, scheduler, and worker processes, not only threads in one process.
- [ ] Test overlapping DuckDB read-only and writable requests against the pinned version; define coordination and error handling for driver access-mode/file-lock restrictions without adding a connection pool.
- [ ] Use staged output and validation before replacing a live model or publishing a backup record. On failure, retain the previous valid model/backup and clean up only artifacts created by the failed operation.

## 2. Model lifecycle functions

Functions below are in `app/routers/models/methods.py` unless otherwise stated.

| Operation | Existing function(s) | Current SQLite dependency | Planned change |
| --- | --- | --- | --- |
| Create | `add_new_model`, `get_template_sql_file` | Creates a `.sqlite3` path with `sqlite3.connect()` and executes a SQLite template script. | Resolve the requested/template engine, create with the correct driver and schema, persist engine metadata, and remove incomplete files on failure. Keep legacy creation on SQLite. |
| Copy / Save As | `save_as_model` | Allocates a `.sqlite3` destination and runs APSW `VACUUM INTO`. | Copy a consistent snapshot using the source engine, preserve `db_type`, and retain the requested destination owner/project/name. Do not leave a master record pointing at an incomplete copy. |
| Manual backup | `create_model_backup` | Uses APSW `VACUUM INTO` and a `.sqlite3` backup filename. Prunes an old backup before creating the new one. | Create and verify an engine-specific snapshot first; record its engine association; then apply retention. A failed new backup must not destroy the last usable backup. |
| Restore backup | `restore_model_from_backup` | Opens source and destination with APSW and uses the SQLite backup API. | Validate the backup engine and model association, exclude competing access, restore through the correct helper, and reopen successfully before reporting success. Reject engine mismatch instead of treating restore as conversion. |
| Download / export model file | `download_model` | Creates a temporary file using APSW `VACUUM INTO`. | Produce a consistent snapshot with the correct engine and filename. Manage temporary-file cleanup after the response finishes. |
| Upload / replace model | `upload_model` | Loads the uploaded file and copies it into the model with the APSW backup API. | Validate the file with the expected engine before changing the live database; reject invalid or mismatched files; replace safely and clean up staging files. |
| Vacuum / maintenance | `vacuum_model` | Runs SQLite `VACUUM` and `PRAGMA wal_checkpoint(TRUNCATE)` directly through APSW. | Retain SQLite maintenance. Define and verify the intended DuckDB maintenance behavior; do not assume SQLite vacuum, DuckDB vacuum, and checkpoint provide equivalent compaction. Use explicit write access and appropriate transaction boundaries. |
| Delete | `delete_model` | Opens the file with `sqlite3`, removes files, and calls `remove_connection_object(model_id)`. | Close/invalidate SQLite pool entries by `model_path` before file deletion: the pool is keyed by path, not model ID. Coordinate active DuckDB contexts without pooling. Remove associated backups safely and preserve non-owner unlink behavior. |
| Rename / move / share / permissions | `rename_model`, `move_model_to_project`, `share_model`, `update_model_access_level` | Primarily updates metadata in the master SQLite database. | Keep these operations on master SQLite. Verify engine metadata and model-file identity remain unchanged; do not introduce unnecessary model-database connections. |
| List backups / model information | `get_model_backups`, `get_model_info`, `get_user_models_by_project` | Reads master metadata. | Keep master SQLite reads. Expose engine information where needed to identify artifacts and supported actions without opening a model with the wrong driver. |

### Snapshot and replacement design checks

- [ ] Select and test a supported DuckDB snapshot strategy using the pinned driver version. Do not blindly copy a database file while writes or required recovery state are outstanding.
- [ ] Define close/checkpoint/staging order for DuckDB file copies and replacements and verify behavior after process interruption.
- [ ] Ensure SQLite pool invalidation happens before removing/replacing files, and prevent another request from reacquiring the path during replacement.
- [ ] Validate backups contain both schema and data, including views, defaults, generated columns, sequences, and binary data where supported.
- [ ] Preserve backward compatibility with existing SQLite backup and download files.

## 3. Task lifecycle functions

These functions are in `app/routers/tasks/methods.py`.

| Function | Current dependency | Planned change |
| --- | --- | --- |
| `run_model_task` | Updates parameters through the new cursor, then prepares a task database through a SQLite-specific helper. | Carry `db_type` through snapshot creation, task records, and worker dispatch. Verify the worker receives a complete snapshot after parameter changes commit. |
| `_copy_db_and_upload_to_broker` | APSW `VACUUM INTO` creates the task-input database. | Accept engine information and use the shared snapshot helper before local/broker upload. Preserve artifact type and clean up temporary files. |
| `update_task_output_and_logs` | Restores successful output through two APSW connections and the SQLite backup API. | Resolve the model/output engine and restore through the lifecycle helper. Validate output before replacement and preserve logs, notifications, and lock-release behavior on every failure path. |
| `restore_db` | Restores a selected task result with the APSW backup API. | Use engine-specific restore while retaining task ownership, success-status, model-identity, and running-task checks. |
| `get_diff` | Invokes `SQLITE_DIFF_TOOL` / `sqldiff`. | Keep SQLite diff support. Implement a DuckDB comparison strategy or explicitly report that DuckDB diff is unsupported until implemented. Never send DuckDB files to `sqldiff`. |

- [ ] Audit `celery_app` and dispatched model-task implementations for engine assumptions, input/output naming, and driver installation.
- [ ] Preserve engine metadata when publishing task output, including future remote output handling.

## 4. Scheduled backups and maintenance

These functions are in `scheduler/_tasks/clean_up.py`.

| Function | Planned change |
| --- | --- |
| `vacuum_user_models` | Extend its model lookup to include `db_type` and pass it to maintenance/system-backup operations. Preserve age and retention scheduling. |
| `create_system_backup` | Replace unconditional APSW maintenance, `sqldiff`, `.sqlite3` naming, and raw file copying with engine-specific snapshot/maintenance behavior. Publish the new backup before retiring the previous valid system backup. |
| `_query` | Keep master maintenance explicitly SQLite. If reused for model maintenance, require engine-aware dispatch and write access. |
| `db_cleanup` | Keep master-record cleanup on SQLite and verify associated model/backup cleanup remains engine-neutral. |

- [ ] Update the scheduler query that supplies model IDs and paths to return engine metadata with the legacy SQLite fallback.
- [ ] Verify scheduled maintenance cannot race with API requests, task snapshotting, or output restoration for the same model.

## 5. SQL dialect and caller compatibility

Primary location: `app/routers/tables/queries.py`, plus related table/model/task methods and templates.

- [ ] Replace engine-specific `RETURNING rowid` in column-order and formatting writes with a suitable result contract for each engine. DuckDB rejects the existing implicit-rowid usage.
- [ ] Give `VALUES` tables explicit column aliases instead of relying on SQLite's `column1` name; check Excel sheet-existence and table-type queries.
- [ ] Implement engine-specific Excel serial-date filters instead of sending SQLite `julianday` expressions to DuckDB.
- [ ] Audit generated SQL and templates for other SQLite-only types, functions, pragmas, conflict handling, case-insensitive comparisons, and schema assumptions.
- [ ] Check that DuckDB types/defaults/generated-column metadata work with table editing, Excel import/export, and value conversion.
- [ ] Exercise existing SQL-client callers against DuckDB SELECT, DDL, DML, `RETURNING`, empty results, and affected-row counts. Preserve the current no-double-execution behavior when retrieving descriptions.
- [ ] Preserve explicit `db_access=1` for all model mutations as these callers are adapted.

## 6. Verification and implementation order

1. Synchronize dependencies; finalize engine metadata and lifecycle helper contracts.
2. Implement creation, snapshot/copy, restore/replacement, deletion, and maintenance helpers with failure-path tests.
3. Integrate the model lifecycle functions, including uploaded/downloaded artifacts and backup retention.
4. Integrate task snapshots, worker execution/output, scheduled backups, maintenance, and diff behavior.
5. Complete remaining SQL-dialect changes and run API-level checks for both engines.

Acceptance checks:

- [ ] Existing SQLite models without `db_type` complete create/copy/backup/restore/upload/download/vacuum/delete flows with prior behavior preserved.
- [ ] DuckDB models complete the same supported flows without passing through APSW, `sqlite3`, SQLite pragmas, or `sqldiff`.
- [ ] Create -> write -> copy -> backup -> modify -> restore preserves engine, schema, data, ownership, and model identity.
- [ ] Task input snapshots and restored outputs preserve committed parameter changes and model data for both engines.
- [ ] Invalid uploads, wrong-engine backups, interrupted writes, failed restores, and failed maintenance retain a usable original model and release connections/locks.
- [ ] Concurrent reads/writes and lifecycle operations behave predictably across API, scheduler, and worker processes.
- [ ] DuckDB contexts leave no application pool entries or open connections after success or failure, and files can be reopened or replaced afterwards.
- [ ] SQLite pool entries are closed using the correct path before deletion/replacement.
- [ ] DuckDB read-only contexts reject mutations; DuckDB write and maintenance operations use explicit write access. SQLite connections remain writable regardless of the shared entry point's `db_access` argument, with permissions enforced by callers.
- [ ] A clean dependency install and the connection/API/lifecycle test suites pass before declaring full DuckDB model support complete.
