get_table_groups = """select GroupName, TableName, TableDisplayName, rowid
                        FROM S_TableGroup
                        ORDER BY 4;"""

get_table_group_from_sqlite_master = """select CASE WHEN type = 'table' THEN 'All Tables'
                                        WHEN type = 'view' THEN 'All Views'
                                        END as TableGroup,  name as TableName, name as TableDisplayName, 1 as rowid
                                        from sqlite_master
                                        WHERE type in ('view', 'table')
                                        ORDER BY 1, 2;"""
