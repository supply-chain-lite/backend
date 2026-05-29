get_model_id_and_paths = """SELECT modelid, modelpath,
        json_extract(ifnull(JsonData, '{}'), '$.last_vacuum_date') as last_vacuum_date
        FROM S_Models;"""

update_vacuum_date = """UPDATE S_Models
        SET JsonData = json_set(COALESCE(JsonData, '{}'), '$.last_vacuum_date', ?)
        WHERE ModelId = ?"""
