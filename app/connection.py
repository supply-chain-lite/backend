import os
import threading
import traceback

import apsw

from .config import master_db

connection_pool = {}
_pool_lock = threading.Lock()


class sql_connection:
    def __init__(self, db_id, db_path):
        self.cursor = get_cursor(db_path)
        self.db_id = db_id

    def __enter__(self):
        self.cursor.execute("BEGIN")
        return this_cursor(self.cursor, self.db_id)

    def __exit__(self, exception_type, exception_value, traceback_val):
        if exception_type:
            try:
                self.cursor.execute("ROLLBACK")
            except Exception as _e:
                pass  # Rollback best-effort; connection will be closed next
            self.cursor.close()

            if issubclass(exception_type, apsw.ReadOnlyError):
                raise apsw.ReadOnlyError(
                    "Sorry!, You have Read Only access."
                ) from exception_value
            print(
                f"some error happened {exception_type} {exception_value} {str(traceback_val)}"
            )
            traceback.print_exc()
            traceback_str = "".join(
                traceback.format_exception(
                    exception_type, exception_value, traceback_val
                )
            )
            print(traceback_str)
            raise
        else:
            try:
                self.cursor.execute("COMMIT")
            except Exception as ex:
                print(f"again error occured {ex}")
                self.cursor.close()
                raise
            self.cursor.close()


def get_cursor(db_path):
    thread_id = threading.get_ident()
    with _pool_lock:
        if db_path in connection_pool and thread_id in connection_pool[db_path]:
            connection = connection_pool[db_path][thread_id]
            return connection.cursor()

        connection = init_db(db_path)
        if db_path in connection_pool:
            connection_pool[db_path][thread_id] = connection
        else:
            connection_pool[db_path] = {thread_id: connection}

        return connection.cursor()


def init_db(db_path, db_access=1):
    if not os.path.isfile(db_path):
        raise Exception(f"DBFile Doesn't exists in system, {db_path}")
    if db_access == 0:
        conn = apsw.Connection(db_path, flags=apsw.SQLITE_OPEN_READONLY)
    else:
        conn = apsw.Connection(db_path, flags=apsw.SQLITE_OPEN_READWRITE)
    conn.setbusytimeout(30000)
    conn.cursor().execute("PRAGMA journal_mode=WAL;")
    conn.cursor().execute("PRAGMA synchronous=NORMAL;")
    conn.cursor().execute("PRAGMA temp_store =  MEMORY")
    return conn


class this_cursor:
    def __init__(self, conn, id):
        self.conn = conn
        self.id = id

    def rowcount(self):
        count_query = "SELECT CHANGES()"
        self.conn.execute(count_query)
        return self.conn.fetchone()[0]

    def execute(self, query, args=tuple()):
        try:
            self.conn.execute(query, args)
        except Exception:
            print(query)
            raise
        return self.conn

    def description(self):
        return self.conn.description

    def intermediate_commit(self):
        try:
            self.conn.execute("COMMIT")
            self.conn.execute("BEGIN")
        except Exception:
            raise


def close_all_conn():
    with _pool_lock:
        conns = list(
            conn
            for by_thread in connection_pool.values()
            for conn in by_thread.values()
        )

        connection_pool.clear()
    for conn in conns:
        conn.close()


def remove_connection_object(id):
    with _pool_lock:
        if id in connection_pool:
            for thread_id in connection_pool[id]:
                conn = connection_pool[id][thread_id]
                conn.close()
            del connection_pool[id]


def master_connection():
    return sql_connection("master", master_db)
