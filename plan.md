# Support DuckDB for non-master models — remaining work

The uncommitted diff already adds a `sqlite`/`duckdb` backend abstraction (`app/connection_duckdb.py`, `app/connection_sqlite.py`, `app/connection.py`) and correctly detects a DB file's engine from its header (`detect_db_type`) for ordinary queries (`sql_connection`, `sql_client`). That part already works generically for any model file, not just `master_db`.

The SQLite-only bracket (`[identifier]`) quoting in `app/routers/tables/queries.py` and `app/routers/tasks/queries.py` has already been fixed (converted to double-quote quoting, which both engines support). That work is **done** and not part of the remaining items below.

However, every place that creates, copies, backs up, restores, vacuums, uploads, downloads, or diffs a **model** file is still hardcoded to SQLite/APSW and bypasses the backend abstraction entirely:

- `app/routers/models/methods.py`: `add_new_model` (`sqlite3.connect`, hardcoded `.sqlite3`), `save_as_model`, `create_model_backup`, `download_model` (all `apsw.Connection(...).execute("VACUUM INTO ...")`), `restore_model_from_backup`, `upload_model` (`apsw.Connection(...).backup(...)`), `delete_model` (`sqlite3.connect`), `vacuum_model` (`apsw` + `PRAGMA wal_checkpoint(TRUNCATE)`).
- `app/routers/tasks/methods.py`: `_copy_db_and_upload_to_broker`, `update_task_output_and_logs`, `restore_db` (all APSW backup/VACUUM INTO), `get_diff` (shells out to `sqldiff.exe`, SQLite-only).

There is also no way today to choose DuckDB when creating a new model (`S_Models` has no engine column, and templates in `S_ModelTemplates` only store one SQLite-flavored SQL file per template).

## Decisions confirmed with the user

- New-model creation gets an explicit `db_type` field (`"sqlite" | "duckdb"`), defaulting to `"sqlite"`.
- Templates need separate DuckDB-flavored SQL files/columns; a template that has no DuckDB SQL simply can't be created as a DuckDB model.
- The model diff feature (`sqldiff.exe`) stays SQLite-only; DuckDB models get a clear "not supported" error from that endpoint.

## Proposed changes

### 1. Schema (`app/database.py`)

- Add `DbType TEXT NOT NULL DEFAULT 'sqlite'` to `create_models_table`, plus a guarded `ALTER TABLE S_Models ADD COLUMN DbType ...` migration for already-initialized master DBs (check `pragma_table_info` before altering, matching the existing guarded-insert style used elsewhere in this file).
- Add nullable `TemplateDuckDBSQL TEXT` and `TemplateWithDataDuckDBSQL TEXT` columns to `create_model_templates_table`, with the same guarded migration approach. Update the `insert_model_template` call for the seeded "Generic Data Model" template to also register a DuckDB SQL file once it exists (step 2).

### 2. DuckDB template file

- Add `app/schemas/generic_model_duckdb.sql`: a DuckDB-compatible rewrite of `app/schemas/generic_model.sql` (DuckDB `SEQUENCE`/identity columns instead of `AUTOINCREMENT`, drop the SQLite-only `PRAGMA foreign_keys`, adjust default-timestamp expressions).

### 3. Backend-level primitives (`app/connection_sqlite.py`, `app/connection_duckdb.py`)

Add matching module-level functions to both backends so `app/connection.py` can dispatch on `detect_db_type`:

- `create_database(db_path, script_path)`: open a **new** file and execute the template script. SQLite keeps today's `sqlite3.connect` + `executescript` behavior; DuckDB opens via `duckdb.connect`, extracts statements via `cursor.extract_statements`, and executes them one by one (mirroring the existing `Cursor.executescript` logic already in `connection_duckdb.py`).
- `copy_out(db_path, dest_path)` (live file → new file, used for backup/save-as/download/task-snapshot): SQLite keeps the existing `apsw.Connection(db_path).execute("VACUUM INTO ...")`. DuckDB: open a connection, run `CHECKPOINT`, close it, then `shutil.copyfile(db_path, dest_path)`.
- `copy_in(source_path, db_path)` (new/backup file → overwrite live model file, used for restore/upload/merging task output back): SQLite keeps the existing `apsw` `.backup("main", ...)` streaming copy. DuckDB: open `source_path`, run `CHECKPOINT`, close it, then `shutil.copyfile(source_path, db_path)`.
- `vacuum(db_path)`: SQLite keeps `VACUUM` + `PRAGMA wal_checkpoint(TRUNCATE)`. DuckDB: `VACUUM` + `CHECKPOINT`.

### 4. Dispatcher (`app/connection.py`)

Add thin wrappers that: (1) call `remove_connection_object` to drop any pooled connection for the affected path(s) so DuckDB's exclusive file lock can't conflict with the copy, then (2) look up the engine via `detect_db_type` (or an explicit `db_type` argument when the destination doesn't exist yet) and call the matching backend primitive:

- `create_model_database(db_type, db_path, script_path)`
- `copy_model_out(model_id, model_path, dest_path)`
- `copy_model_in(model_id, source_path, model_path)`
- `vacuum_model_database(model_id, model_path)`

### 5. Call-site updates

- `app/routers/models/methods.py`:
  - `add_new_model`: accept `db_type`, pick the matching template column (`TemplateSQL`/`TemplateWithDataSQL` vs `TemplateDuckDBSQL`/`TemplateWithDataDuckDBSQL`, raise 400 if the requested engine has no template SQL), use `.duckdb`/`.sqlite3` extension per engine, call `create_model_database`, and store `db_type` in the `S_Models` insert (update `insert_models` query + `S_Models` schema usage).
  - `save_as_model`, `create_model_backup`, `download_model`: replace `apsw.Connection(...).execute("VACUUM INTO ...")` with `copy_model_out`; choose the backup/new-model file extension from the source model's detected engine.
  - `restore_model_from_backup`, `upload_model`: replace the `apsw` `.backup()` calls with `copy_model_in`.
  - `delete_model`: drop the `sqlite3.connect(...); conn.close()` no-op (or replace with `remove_connection_object` if its purpose was releasing a lock before `os.remove`).
  - `vacuum_model`: replace with `vacuum_model_database`.
- `app/routers/tasks/methods.py`:
  - `_copy_db_and_upload_to_broker`, `update_task_output_and_logs`, `restore_db`: replace APSW backup/VACUUM INTO calls with `copy_model_out`/`copy_model_in` as appropriate.
  - `get_diff`: detect the model's engine first; if DuckDB, raise `HTTPException(400, "SQL diff is not supported for DuckDB models")` before invoking `sqldiff.exe`.
- `app/routers/models/schemas.py`: add `db_type: Literal["sqlite", "duckdb"] = "sqlite"` to `createModelRequest`.
- `app/routers/models/router.py`: pass `request.db_type` through to `add_new_model`.

## Out of scope

- No changes to the `sql_client` execution path (already backend-agnostic).
- No DuckDB-flavored versions of any templates other than "Generic Data Model" (other templates simply won't offer DuckDB as an option until their SQL is authored).
