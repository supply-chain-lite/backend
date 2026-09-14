-- Generic data model for DuckDB.
BEGIN TRANSACTION;

CREATE SEQUENCE s_datafiles_fileid_seq START 1;
CREATE SEQUENCE s_taskmaster_taskid_seq START 1;
CREATE SEQUENCE t_tasklogs_id_seq START 1;

-- Table: S_DataFiles
CREATE TABLE S_DataFiles (
    FileId              INTEGER NOT NULL PRIMARY KEY DEFAULT nextval('s_datafiles_fileid_seq'),
    FileName            VARCHAR NOT NULL,
    FileType            VARCHAR NOT NULL,
    FileExtension       VARCHAR NOT NULL,
    UploadedFileName    VARCHAR,
    FileBlob            BLOB,
    LastUpdated         TIMESTAMP DEFAULT current_localtimestamp(),
    UNIQUE(FileName)
);

-- Table: S_TableGroup
CREATE TABLE S_TableGroup (
    GroupName        VARCHAR,
    TableName        VARCHAR,
    TableDisplayName VARCHAR,
    TableType        VARCHAR,
    ColumnOrder      VARCHAR,
    Table_Status     VARCHAR,
    Freeze_Col_Num   NUMERIC
);
INSERT INTO S_TableGroup (GroupName, TableName, TableDisplayName, TableType, ColumnOrder, Table_Status, Freeze_Col_Num) VALUES ('Log Tables', 'T_TaskLogs', 'Task Logs', 'Task Logs', NULL, 'Active', NULL);
INSERT INTO S_TableGroup (GroupName, TableName, TableDisplayName, TableType, ColumnOrder, Table_Status, Freeze_Col_Num) VALUES ('Log Tables', 'T_SolverLog', 'Solver Logs', 'Solver Logs', NULL, 'Active', NULL);
INSERT INTO S_TableGroup (GroupName, TableName, TableDisplayName, TableType, ColumnOrder, Table_Status, Freeze_Col_Num) VALUES ('Setups', 'S_TableGroup', 'Table Group', 'Input', NULL, 'Active', NULL);
INSERT INTO S_TableGroup (GroupName, TableName, TableDisplayName, TableType, ColumnOrder, Table_Status, Freeze_Col_Num) VALUES ('Setups', 'S_TableParameters', 'Table Parameters', 'Input', NULL, 'Active', NULL);
INSERT INTO S_TableGroup (GroupName, TableName, TableDisplayName, TableType, ColumnOrder, Table_Status, Freeze_Col_Num) VALUES ('Setups', 'S_TaskMaster', 'Task Master', 'Input', NULL, 'Active', NULL);
INSERT INTO S_TableGroup (GroupName, TableName, TableDisplayName, TableType, ColumnOrder, Table_Status, Freeze_Col_Num) VALUES ('All Other', 'V_TEMPV', 'Temp View', 'Output', NULL, 'Active', NULL);

-- Table: S_TableParameters
CREATE TABLE S_TableParameters (
    TableName      VARCHAR,
    ColumnName     VARCHAR,
    ParameterType  VARCHAR,
    ParameterValue VARCHAR,
    UNIQUE(TableName, ColumnName, ParameterType)
);

-- Table: S_TaskMaster
CREATE TABLE S_TaskMaster (
    TaskId             INTEGER NOT NULL PRIMARY KEY DEFAULT nextval('s_taskmaster_taskid_seq'),
    TaskName           VARCHAR,
    TaskDisplayName    VARCHAR,
    TaskType           VARCHAR DEFAULT 'PythonScript',
    TaskParameters     VARCHAR,
    TaskStatus         VARCHAR,
    TaskLastRunDate    VARCHAR,
    TaskOutput         VARCHAR
);

-- Table: T_QueryLogs
CREATE TABLE T_QueryLogs (
    LogTime      VARCHAR DEFAULT (CAST(current_localtimestamp() AS VARCHAR)),
    QuerySQL     VARCHAR,
    QueryMsg     VARCHAR
);

-- Table: T_SolverLog
CREATE TABLE T_SolverLog (
    LogTime    VARCHAR DEFAULT (CAST(current_localtimestamp() AS VARCHAR)),
    LogMessage VARCHAR
);

-- Table: T_TaskLogs
CREATE TABLE T_TaskLogs (
    ID              INTEGER PRIMARY KEY DEFAULT nextval('t_tasklogs_id_seq'),
    TaskId          VARCHAR,
    TaskName        VARCHAR NOT NULL,
    ProcessId       VARCHAR,
    TaskStatus      VARCHAR,
    StartDate       VARCHAR DEFAULT (CAST(current_localtimestamp() AS VARCHAR)),
    EndDate         VARCHAR,
    ErrorMsg        VARCHAR,
    Alerted         INTEGER DEFAULT 0,
    TaskDbId        VARCHAR,
    MasterTaskId    VARCHAR
);

-- View: V_TEMPV
CREATE VIEW V_TEMPV AS SELECT 1;

COMMIT TRANSACTION;
