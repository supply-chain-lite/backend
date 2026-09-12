# Support DuckDB for non-master models — implementation plan

The backend already has a `sqlite`/`duckdb` abstraction in `app/connection.py`, `app/connection_sqlite.py`, and `app/connection_duckdb.py`. Connection dispatch and much of the query path support both engines, and SQLite-only bracket quoting in `app/routers/tables/queries.py` and `app/routers/tasks/queries.py` has been fixed. Application SQL still needs compatibility fixes; the abstraction does not translate SQL dialects.

Model lifecycle operations remain SQLite-specific: create, copy, backup, restore, vacuum, upload, download, delete, and diff. The affected code includes `app/routers/models/methods.py`, `app/routers/tasks/methods.py`, and `scheduler/_tasks/clean_up.py`. Model and template engine metadata will use the existing `JsonData` columns in `S_Models` and `S_ModelTemplates`.

`delete_model` already calls `remove_connection_object` before `os.remove`. This plan introduces a shared lifecycle API, with coordination that prevents other requests or processes from reopening a model during a file operation. Closing the current process's pool alone is insufficient.

## Decisions

- New-model creation derives its engine from the selected template's `S_ModelTemplates.JsonData.db_type` (`"sqlite" | "duckdb"`). If the template metadata has no `db_type`, assume `"sqlite"`. No independent engine selector is added to the creation request.
- The master database remains SQLite. For existing model files, the file signature is authoritative; the `db_type` key in `S_Models.JsonData` records the verified engine for metadata and capability checks, for example `{"db_type": "duckdb"}`. Extensions are naming conventions only.
- Each template uses its existing `TemplateSQL` and `TemplateWithDataSQL` fields for its declared engine. No additional DuckDB template columns, bundled SQL file, or separate seeded template is required by this plan. The registered scripts must be compatible with the template's engine.
- The SQL diff feature stays SQLite-only; DuckDB models return a clear "not supported" error from that endpoint.
- Upload, backup restore, and task output replacement must keep the target model's engine. Cross-engine replacement or conversion is rejected before changing the live file.
- DuckDB access to each model is serialized across API and scheduler processes initially. All participating code uses the same per-model lock, and DuckDB handles are closed before releasing it. Different models can still be used concurrently.
- DuckDB task execution requires an explicitly compatible task program. Existing task registrations default to SQLite-only until verified.

## Proposed changes

### 1. Model and template metadata (`app/database.py`, `app/routers/models/queries.py`)

- Store `db_type` (`"sqlite"` or `"duckdb"`) inside the existing `S_Models.JsonData` JSON object. No separate engine column or `S_Models` schema alteration is required. New model inserts must explicitly write the verified engine, including the default SQLite case.
- Backfill `$.db_type` from existing model file signatures, including DuckDB files with SQLite-looking extensions. Use `json_set(COALESCE(JsonData, '{}'), '$.db_type', ?)` to preserve other metadata such as `IsLocked` and maintenance dates. A missing key requires detection rather than assuming the file is SQLite. Log missing/unrecognized files and malformed or non-object JSON without overwriting their metadata or preventing unrelated rows from migrating; affected operations must return a clear validation error.
- Read template `db_type` from `S_ModelTemplates.JsonData`. Null `JsonData`, an absent key, or a JSON null value defaults to `"sqlite"`; after validating that metadata is a JSON object, use `COALESCE(json_extract(JsonData, '$.db_type'), 'sqlite')`. Reject unsupported values and malformed/non-object JSON with a clear template configuration error.
- Keep `TemplateSQL`, `TemplateWithDataSQL`, and the existing Generic Data Model seed unchanged. Existing templates need no metadata backfill because the missing-key default preserves SQLite behavior. A template marked `{"db_type": "duckdb"}` uses the scripts already registered in those fields.
- No table schema alterations are needed for engine metadata. Model metadata backfills must be safe to repeat, and any template JSON updates must preserve unrelated keys.
- Update `insert_models` and model metadata queries to write `$.db_type` and read it with `json_extract(S_Models.JsonData, '$.db_type') AS db_type`, including save-as. Save-as records the verified source engine in the new model's JSON without copying transient task-lock state. All JSON updates must preserve unrelated keys. At runtime, detect and report a metadata/signature mismatch rather than selecting a driver from stale metadata; repair only `$.db_type` after successful validation.

### 2. Template resolution and execution

- Extend template lookup to return the resolved engine together with the existing script path. Select `TemplateSQL` or `TemplateWithDataSQL` using `with_sample_data`, preserving current template access checks and path resolution.
- Execute the selected script using the resolved engine. Do not translate the script, try another engine, or fall back from a requested sample-data script when it is unavailable. Invalid engine metadata or a missing/incompatible script must fail creation cleanly.
- Record the successfully created file's verified engine in `S_Models.JsonData.db_type`. Later template metadata changes do not change the engine of existing model files.
- Use temporary test fixtures to cover DuckDB-compatible schemas, date serialization, and generated IDs, including an insert after backup/restore. This does not require adding a production DuckDB template or changing the Generic Data Model seed.
- Define transaction ownership for template execution so the script and creator do not issue nested `BEGIN` statements. Failed creation must leave no registered model or partial database.

### 3. Backend-specific database lifecycle APIs

Add matching functions to both `app/connection_sqlite.py` and `app/connection_duckdb.py`. Each function owns the engine-specific driver logic for exactly one operation. These are internal helpers invoked under the dispatcher's model-access guard.

- `create_database(db_path, script_path)` — create a new model file and run the template script.
- `copy_database_out(db_path, dest_path)` — copy a live model file to a new destination (backup, save-as, download, task snapshot).
- `copy_database_in(source_path, db_path)` — validate and replace database contents from a source of the same engine (restore, upload, task output replacement). This replaces the whole database; it is not a row-level merge.
- `vacuum_database(db_path)` — vacuum/checkpoint a model file.
- `delete_database(db_path)` — remove the model file and any engine-specific sidecar files after the caller has ensured no handle is open.

SQLite implementations use `sqlite3`/`apsw`: retain consistent snapshots through `VACUUM INTO` or `.backup()`, transactional restore through `.backup()`, and SQLite maintenance through `VACUUM` and `PRAGMA wal_checkpoint(TRUNCATE)`. Do not replace SQLite snapshots with a raw copy of a live file that may have uncheckpointed WAL data.

DuckDB snapshots require exclusive model access for the complete checkpoint/close/copy interval. Run `CHECKPOINT`, close all handles, copy to a staging file, and verify that the copy opens independently. A checkpoint alone does not prevent subsequent writes. Treat DuckDB maintenance as checkpointing; do not promise SQLite-equivalent file shrinking.

Replacement contract:

- Verify that source and target are distinct, the source exists, its signature matches the target engine, and it opens successfully with the expected application metadata tables. Use restricted connections when inspecting uploads. Reject invalid, truncated, incompatible, or incomplete artifacts before touching the target.
- Require a self-contained source snapshot. Recover/checkpoint task output only after its producer has closed it; never silently discard a source WAL containing committed changes.
- For DuckDB, build and validate a replacement in the target directory, then atomically replace the closed target while holding its lock. Retain a recoverable original until replacement bookkeeping succeeds. Handle old target sidecars only after clean closure; never leave an old WAL alongside a new database.
- Keep the SQLite backup transaction's rollback guarantees. Stage and validate input before starting the restore, and preserve a recovery snapshot when needed for metadata failure recovery.
- Clean up staging files and newly created sidecars on failure. A failed operation must preserve the original usable database and must not register a successful backup or replacement.
- Define compensation/recovery for filesystem success followed by a failed master-database commit. The two resources cannot be committed in one transaction. Keep recovery artifacts until success is recorded.
- Copy-out destinations must be new paths; adapt temporary-file callers accordingly. Publish completed artifacts only after validation, and retain the previous backup until the new backup is registered.

### 4. Dispatcher wrappers in `app/connection.py`

Add wrappers that acquire exclusive lifecycle access, validate the relevant paths and engines, drain/close affected handles, then delegate to the correct backend:

- `create_model_database(db_type, db_path, script_path)`
- `copy_model_out(model_path, dest_path)`
- `copy_model_in(source_path, model_path)`
- `vacuum_model_database(model_path)`
- `delete_model_database(model_path)`

The methods in routers and scheduled maintenance only call these wrappers; they do not open model files with `sqlite3` or `apsw` themselves. Creation passes the engine resolved from template metadata because no file signature exists yet. Missing-file deletion is idempotent; it must not require detecting a nonexistent file.

Connection and process coordination is part of this step:

- Introduce a stable per-model lock identity shared by API workers, scheduler jobs, and lifecycle operations. Use a tested cross-platform interprocess locking primitive that releases ownership on process exit; do not use the replaceable database file itself as the lock file.
- For DuckDB, acquire the model lock before opening any connection or creating a cursor, retain it through commit/rollback and cursor closure, and close all unique database handles before releasing it. Disable idle pooled DuckDB handles so another process can subsequently open the file. Include scheduled task submission and task output application, not just maintenance.
- For SQLite, ordinary transactions may retain existing concurrency, but lifecycle operations that close handles or delete files must exclude active and newly starting users of the affected model. All callers must participate in the access protocol.
- Do not forcibly close connections underneath active transactions. Use bounded waiting and return a clear busy/retry result when exclusive access cannot be obtained. Closing duplicate pool references must close each underlying handle only once.
- Refactor callers as needed to avoid holding a master write transaction while waiting for model access. Establish a consistent lock/transaction order and recheck permissions and task state after waiting. The existing `IsLocked` task flag is not a replacement for database access coordination.
- Use consistent path normalization and reject source/target aliases. When multiple model locks are required, acquire them in a deterministic order.

### 5. `app/routers/models/methods.py` updates

- `add_new_model`: resolve `db_type` from the selected template's JSON metadata (default SQLite), pick the existing `TemplateSQL` or `TemplateWithDataSQL` field, use `.sqlite3` or `.duckdb` extension, and call `create_model_database`. Persist the verified engine in the new model's JSON metadata.
- `save_as_model`: call `copy_model_out`; derive the new file extension from the source engine.
- `create_model_backup`: call `copy_model_out`; use the source engine's extension for the backup file. Apply retention only after a new backup is successfully registered.
- `download_model`: call `copy_model_out` into a new temp download path and use the engine's extension in the download filename.
- `restore_model_from_backup`: call `copy_model_in`.
- `upload_model`: call `copy_model_in` after writing the upload to a temp file.
- `delete_model`: call `delete_model_database` for the live model file, then remove backup files and delete backup rows as today.
- `vacuum_model`: call `vacuum_model_database`.
- Preserve owner/access checks and running-task restrictions. Coordinate create/save-as/delete metadata with file operations and recovery handling; do not leave a model row pointing to a failed artifact.

### 6. `app/routers/tasks/methods.py` updates

- `_copy_db_and_upload_to_broker`: call `copy_model_out` instead of `apsw` `VACUUM INTO`.
- `update_task_output_and_logs`: call `copy_model_in` instead of `apsw` `.backup()`.
- `restore_db`: call `copy_model_in` instead of `apsw` `.backup()`.
- `get_diff`: detect the model engine first and raise `HTTPException(400, "SQL diff is not supported for DuckDB models")` before invoking `sqldiff.exe`.
- Preserve task snapshot engine and generated-ID state throughout local broker staging and execution. Validate both artifacts before SQLite diff, since historical task files can be missing or invalid.
- On output replacement failure, retain the live model and task output, record an actionable failure, and release task locks through the existing cleanup path. Do not report that output was applied successfully.
- Store supported engines in task registration metadata, for example `SC_TaskResolution.JSONData.SupportedDbTypes`, defaulting existing registrations to `["sqlite"]`. Check compatibility before snapshot creation or enqueueing, including scheduled submissions; keep worker-side validation as a second check.
- Audit registered external programs before enabling DuckDB. `../scripts/main.py` uses `sqlite3`, and Supply Planning scripts use APSW/SQLite SQL. A DuckDB template does not make these programs compatible. Use a small verified DuckDB task to exercise the end-to-end path; porting all external programs is a separate project.

### 7. Scheduled maintenance (`scheduler/_tasks/clean_up.py`)

- Update `create_system_backup` to use engine-aware lifecycle wrappers and extensions. Keep direct SQLite maintenance only for the master database.
- Preserve the SQLite `sqldiff` unchanged-model optimization. For DuckDB, skip SQL diff and create a snapshot when the existing maintenance eligibility rules say it is due; do not claim byte comparison is equivalent to a SQL diff.
- Register the completed system backup and maintenance timestamp before removing the previous backup. On failure, retain the previous backup and do not advance the success timestamp.
- Treat model-lock contention as a deferred maintenance attempt, not a successful vacuum. The next scheduler run may retry.
- Ensure folder cleanup cannot remove active task artifacts, staging files, lock files, or pending recovery artifacts solely because their timestamps are old.

### 8. Remaining application SQL compatibility

- In `app/routers/tables/queries.py`, replace `RETURNING rowid` in column-order and formatting writes with a supported success marker such as `RETURNING 1` where callers only check whether a row was affected. Update callers if they depend on a returned identifier.
- In `app/routers/models/queries.py`, replace the `datetime('now')` expression used by `update_file_blob` with an engine-aware timestamp expression or a bound application timestamp, preserving the intended response format.
- These failures were reproduced against DuckDB 1.5.5 during review. Audit application-generated model SQL for other SQLite assumptions, including types, date functions, metadata queries, and implicit row identifiers. Keep SQL that operates only on the SQLite master database unchanged.
- Retain the existing SQL-client dispatch design, but include it in regression checks. Arbitrary user SQL must use the selected engine's dialect; automatic SQL translation is not part of this feature.

### 9. API and routing updates

- Keep `createModelRequest` and the create route's request fields unchanged: template selection determines the engine inside `add_new_model`.
- Expose verified engine information as `db_type` in model metadata responses, read from `S_Models.JsonData` after validation. Provide a backward-compatible way to discover each template's resolved `db_type` and sample-data availability without breaking the existing template-name list response. Template engine metadata defaults to SQLite when absent.
- Translate unsupported engines/templates/tasks, invalid files, engine mismatches, and lock timeouts into clear API errors. Keep driver details in logs where appropriate.

## Implementation order

1. Add repeatable model JSON backfills, template engine resolution with the SQLite default, and the known model-query fixes.
2. Implement and test model-access coordination, including connection closure and master/model transaction ordering.
3. Implement lifecycle helpers with source validation, staging, failure recovery, and engine checks.
4. Integrate model endpoints, task snapshots/output, task compatibility checks, and scheduled maintenance.
5. Run the acceptance checks below and document the supported deployment/locking behavior before enabling DuckDB model creation.

## Acceptance checks

Use temporary databases and directories; do not run destructive checks against user models. Cover both engines unless a check is explicitly engine-specific.

- **Metadata and upgrade:** initialize a fresh master database; upgrade an existing one; rerun initialization; verify the Generic template and existing SQL paths remain unchanged. Verify signature-based model `JsonData.db_type` backfill, null JSON, missing keys, misleading extensions, missing/invalid model files, and malformed/non-object JSON handling. Confirm existing JSON keys survive backfill and later task/maintenance updates preserve `db_type`; create/save-as must persist the correct engine without schema additions. Templates with null metadata or missing/null `db_type` must resolve to SQLite; explicitly marked templates must resolve to the declared engine.
- **Creation and queries:** use the existing SQLite template and a temporary DuckDB template registration whose existing SQL fields reference test scripts. Exercise both schema-only and sample-data paths; verify the engine comes from template JSON and is recorded in model JSON. Reject invalid template metadata, unavailable scripts, and incompatible SQL without leftover rows/files. Confirm later template metadata changes do not alter existing models. Exercise table browsing/editing, column order, formatting, attached-file updates, SQL-client execution, timestamps, and generated IDs.
- **Lifecycle round trips:** save-as, manual backup/restore, download/upload, maintenance, and delete. Verify schemas, data, views, and DuckDB sequence state; reopen every completed snapshot independently. Include SQLite WAL data and DuckDB changes requiring checkpointing.
- **Failed operations:** reject cross-engine, truncated, invalid, and incomplete sources without changing the target. Inject copy, replacement, and master-commit failures; verify the original/recovery artifact remains usable, metadata is consistent or recoverable, and temporary files are cleaned up appropriately.
- **Concurrency:** hold an active model transaction while starting backup/restore/delete; verify bounded waiting without force-closing the active transaction. Exercise simultaneous API/scheduler access in separate processes, concurrent lifecycle requests, process termination, and Windows file replacement. Confirm another process can open DuckDB after a completed operation and that lock ordering does not deadlock with master writes.
- **Tasks:** execute a verified task for each engine, apply output, restore a historical task artifact, and test failure/cancellation cleanup. Reject SQLite-only programs for DuckDB before enqueueing. Confirm DuckDB diff returns the documented error without launching `sqldiff`.
- **Scheduler:** create system backups for both engines, preserve SQLite unchanged-model detection, verify DuckDB bypasses `sqldiff`, and check retention, deferred busy models, and failed backup handling. Run an actual separate scheduler process while the API is active.
- **Regression:** retain access restrictions and existing SQLite behavior, run the project's lint checks, and confirm no unconverted direct model-file lifecycle calls remain in routers or scheduler code.

## Out of scope

- No DuckDB master database, cross-engine conversion, or automatic translation of user-authored SQL.
- No independent engine selector; users select a template and its metadata determines the creation engine.
- No general port of external task programs. Programs remain SQLite-only unless explicitly verified and registered for DuckDB.
- No simultaneous multi-process DuckDB writes to the same native database file; access is serialized through the shared protocol described above.
- No new production template SQL files, separate DuckDB template fields, or changes to the Generic Data Model seed. Template authors are responsible for registering scripts compatible with the engine declared in template JSON metadata.
