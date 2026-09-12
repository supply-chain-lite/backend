get_sql_history = """select SQLQuery, IsErrored, Status, CreatedAt
                    from S_SQLHistory
                    where ModelID = ? and UserEmail = ?
                    order by CreatedAt desc
                    LIMIT 250"""

add_sql_history = """insert into S_SQLHistory (ModelID, UserEmail, ModelName, ProjectName, SQLQuery,
                    IsErrored, Status)
                    values (?, ?, ?, ?, ?, ?, ?)"""
