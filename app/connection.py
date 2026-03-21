import apsw, threading
import os, traceback
#from ..core.config import master_db
from app.CONFIG.config import master_db
from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError

connection_pool = {}


class sql_connection():
    def __init__(self, db_id, db_path):
        self.cursor = get_cursor(db_path)
        self.db_id = db_id
        self.started_transaction = False

    def __enter__(self): 
        conn = self.cursor.getconnection()

        if not conn.in_transaction:
            self.cursor.execute("BEGIN")
            self.started_transaction = True

        return this_cursor(self.cursor, self.db_id)

    def __exit__(self, exception_type, exception_value, traceback_val):
        if exception_type:
            try:
                self.cursor.execute("ROLLBACK")
            except:
                pass
            self.cursor.close()

            # Added, Darshan Shrimali
            if issubclass(exception_type, HTTPException):
                return False   # re-raise original exception

            # Added, Darshan Shrimali
            if issubclass(exception_type, RequestValidationError):
                return False   # re-raise original exception

            if exception_type == apsw.ReadOnlyError:
                raise UserError("Sorry!, You have Read Only access.")
            print(f"some error happened {exception_type} {exception_value} {str(traceback_val)}")
            traceback.print_exc()
            traceback_str = ''.join(traceback.format_exception(exception_type, exception_value,traceback_val))
            print(traceback_str)
            raise UserError(str(exception_value))
        else:
            ex = None
            try:
                self.cursor.execute("COMMIT")
            except Exception as ex:
                print(f"again error occured {ex}")
                self.cursor.close()
                raise Exception(f"Error occured {ex}")
            self.cursor.close()


def get_cursor(db_path):
    thread_id = threading.get_ident()
    if db_path in connection_pool and thread_id in connection_pool[db_path] :
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
        raise UserError(f"DBFile Doesn't exists in system, {db_path}")
    if db_access==0:
        conn = apsw.Connection(db_path,flags=apsw.SQLITE_OPEN_READONLY)
    else:
        conn = apsw.Connection(db_path)
    conn.setbusytimeout(30000)
    conn.cursor().execute("PRAGMA journal_mode=WAL;")          
    conn.cursor().execute("PRAGMA synchronous=NORMAL;")
    conn.cursor().execute("PRAGMA temp_store =  MEMORY")
    return conn
    

class this_cursor():
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
        except Exception as ex:
            print(query)
            raise ex
        return self.conn

    def description(self):
        return self.conn.description    
    
    def intermediate_commit(self):
        try:
            self.conn.execute("COMMIT")
            self.conn.execute("BEGIN")
        except Exception as ex:
            raise Exception(f"Error occured {ex}")
    


class UserError(Exception):
    message: str

    def __init__(self, msg):
        self.message = msg


def close_all_conn():
    for key in connection_pool:
        for thread_id in connection_pool[key]:
            connection_pool[key][thread_id].close()

def remove_connection_object(id):
    if id in connection_pool:
        for thread_id in connection_pool[id]:
            conn = connection_pool[id][thread_id] 
            conn.close()
        del connection_pool[id]

def master_connection():
    return sql_connection("master", master_db)