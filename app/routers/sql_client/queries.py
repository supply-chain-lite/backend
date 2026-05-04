get_sql_objects = """select type, name from sqlite_master
                     where type in ('table', 'view') COLLATE NOCASE
                     ORDER BY 1, 2"""

get_object_ddl = """select sql from sqlite_master
                    where name = ? COLLATE NOCASE"""

get_sql_history = """select SQLQuery, IsErrored, Status, CreatedAt
                    from S_SQLHistory
                    where ModelID = ? and UserEmail = ?
                    order by CreatedAt desc
                    LIMIT 250"""

add_sql_history = """insert into S_SQLHistory (ModelID, UserEmail, ModelName, ProjectName, SQLQuery,
                    IsErrored, Status)
                    values (?, ?, ?, ?, ?, ?, ?)"""
