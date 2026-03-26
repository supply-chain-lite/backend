BEGIN TRANSACTION;

---- CL TABLES Start
CREATE TABLE T_QueryLogs (
	LogTime      VARDATE DEFAULT (datetime('now', 'localtime') ),
	QuerySQL     VARCHAR,
	QueryMsg     VARCHAR
);

CREATE TABLE T_TaskLogs (
        ID              INTEGER PRIMARY KEY AUTOINCREMENT,
        TaskId          VARCHAR,
        TaskName        VARCHAR NOT NULL,
        ProcessId       VARCHAR,
        TaskStatus      VARCHAR,
        StartDate       VARDATE DEFAULT (datetime('now', 'localtime') ),
        EndDate         VARCHAR,
        ErrorMsg        VARCHAR,
        Alerted         INTEGER DEFAULT (0),
        TaskDbId        VARCHAR,
        MasterTaskId    VARCHAR
);

CREATE TABLE T_SolverLog (
    LogTime    VARCHAR DEFAULT (datetime('now', 'localtime') ),
    LogMessage VARCHAR
);

CREATE TABLE S_ModelParams (
    ParamName    VARCHAR,
    ParamValue   VARCHAR
);

CREATE TABLE S_TableParameters (
    TableName      VARCHAR,
    ColumnName     VARCHAR,
    ParameterType  VARCHAR,
    ParameterValue VARCHAR,
    UNIQUE(TableName,ColumnName,ParameterType)
);

CREATE TABLE S_TableGroup (
    GroupName        VARCHAR,
    TableName        VARCHAR,
    TableDisplayName VARCHAR,
    TableType        VARCHAR,
    ColumnOrder      VARCHAR,
    Table_Status     VARCHAR,
    Freeze_Col_Num   NUMERIC
);

CREATE TABLE S_TaskMaster (
	TaskId	            INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
	TaskName	        VARCHAR,
	TaskDisplayName	    VARCHAR,
    TaskType            VARCHAR,
	TaskParameters	    VARCHAR,
	TaskStatus	        VARCHAR,
	TaskLastRunDate	    VARCHAR,
	TaskOutput	        VARCHAR
);


CREATE TABLE S_DataFiles (
	FileId	            INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
	FileName	        VARCHAR,
	FileType   	        VARCHAR,
    FileBlob            BLOB NOT NULL,
	Status	            VARCHAR DEFAULT ('Active'),
    UNIQUE(FileName,FileType)	
);

-- Table: S_NotebookContent
CREATE TABLE S_NotebookContent (
    CellId         INTEGER NOT NULL
                           PRIMARY KEY AUTOINCREMENT,
    Name           VARCHAR,
    NotebookId     INTEGER NOT NULL,
    CellContent    VARCHAR,
    CellType       VARCHAR,
    CreationDate   VARCHAR DEFAULT (datetime('now', 'localtime') ),
    LastUpdateDate VARCHAR DEFAULT (datetime('now', 'localtime') ) 
);


-- Table: S_Notebooks
CREATE TABLE S_Notebooks (
    NotebookId     INTEGER NOT NULL
                           PRIMARY KEY AUTOINCREMENT,
    Name           VARCHAR,
    Type           VARCHAR,
    Status         VARCHAR DEFAULT 'Active',
    CreationDate   VARCHAR DEFAULT (datetime('now', 'localtime') ),
    LastUpdateDate VARCHAR DEFAULT (datetime('now', 'localtime') ) 
);


CREATE TABLE S_PackageWheels (
	WheelId	            INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
	WheelName	        VARCHAR UNIQUE,
    WheelBlob            BLOB NOT NULL,
	Status	            VARCHAR DEFAULT ('Active')	
);

CREATE VIEW V_TEMPV
AS SELECT 1;


INSERT INTO S_ModelParams (ParamName, ParamValue) VALUES ('ModelIcon', 'fas fa-cube');
INSERT INTO S_ModelParams (ParamName, ParamValue) VALUES ('ModelName', 'Supply Planning DB');
INSERT INTO S_ModelParams (ParamName, ParamValue) VALUES ('DBVersion', '1.0.3');

---- CL TABLES End

-- Table: I_ItemMaster
CREATE TABLE I_ItemMaster (
    ItemId                VARCHAR,
    ItemDescription       VARCHAR,
    ItemType              VARCHAR,
    SalesPrice            NUMERIC,
    UnitCost              NUMERIC,
    Brand                 VARCHAR,
    SubBrand              VARCHAR,
    Category              VARCHAR,
    SubCategory           VARCHAR,
    ItemStatus            INTEGER DEFAULT 1 
);

-- Table: I_LocationMaster
CREATE TABLE I_LocationMaster (
    LocationId          VARCHAR,
    LocationType        VARCHAR,
    LocationCategory    VARCHAR,
    LocationAttribute1  VARCHAR,
    LocationAttribute2  VARCHAR,
    Region              VARCHAR,
    Country             VARCHAR,
    State               VARCHAR,
    City                VARCHAR,
    ZipCode             VARCHAR,
    Longitude           NUMERIC,
    Latitude            NUMERIC
);

-- Table: I_ModelSetup
CREATE TABLE I_ModelSetup (
    ModelName        VARCHAR,
    StartDate        VARDATE,
    TimeFrequency    VARCHAR,
    NumberOfPeriods  NUMERIC,
    InterestRate     NUMERIC DEFAULT (0.12),
    DOSWindowStartPeriod INTEGER DEFAULT (1) 
);

-- Table: I_BOMRecipe
CREATE TABLE I_BOMRecipe (
    BOMId           VARCHAR,
    ItemId          VARCHAR,
    LocationId      VARCHAR,
    UsageQuantity   NUMERIC
);

-- Table: I_ForecastOrders
CREATE TABLE I_ForecastOrders (
    OrderId             VARCHAR,
    ItemId              VARCHAR,
    LocationId          VARCHAR,
    ForecastArrivalDate VARDATE,
    Quantity            NUMERIC,
    SalesPrice          NUMERIC
);

-- Table: I_InventoryPolicy
CREATE TABLE I_InventoryPolicy (
    ItemId                      VARCHAR,
    LocationId                  VARCHAR,
    InventoryType               VARCHAR,
    IsProduction                INTEGER DEFAULT 0,
    IsStorage                   INTEGER DEFAULT 0,
    InventoryUnitCost           NUMERIC,
    InventoryHoldingCost        NUMERIC,
    SalesPrice                  NUMERIC,
    SafetyStockDOS              NUMERIC DEFAULT (0),
    DOSWindow                   NUMERIC DEFAULT (0),
    InventoryShelfLife          NUMERIC,
    MinReleaseTime              NUMERIC,
    MinEndingInventory          NUMERIC DEFAULT (0),
    MaxEndingInventory          VARCHAR DEFAULT ('INF'),
    MinProductionQuantity       NUMERIC DEFAULT (0),
    MaxProductionQuantity       VARCHAR DEFAULT ('INF'),
    InventoryStatus             INTEGER DEFAULT (1)
);

-- Table: I_InventoryPolicyPerPeriod
CREATE TABLE I_InventoryPolicyPerPeriod (
    ItemId                VARCHAR,
    LocationId            VARCHAR,
    StartDate             VARDATE,
    MinEndingInventory    NUMERIC DEFAULT (0),
    MaxEndingInventory    VARCHAR DEFAULT ('INF'),
    MinProductionQuantity NUMERIC DEFAULT (0),
    MaxProductionQuantity VARCHAR DEFAULT ('INF'),
    SafetyStockDOS        NUMERIC
);

-- Table: I_Processes
CREATE TABLE I_Processes (
    ProcessId          VARCHAR,
    ProcessStep        VARCHAR,
    ItemId             VARCHAR,
    LocationId         VARCHAR,
    BOMId              VARCHAR,
    ResourceId         VARCHAR,
    UnitOperationTime  NUMERIC,
    UnitOperationCost  NUMERIC,
    Yield              NUMERIC DEFAULT 1,
    MOQ                NUMERIC,
    PersonnelTime      NUMERIC,
    LotSizeRounding    NUMERIC,
    MinSplitRatio      NUMERIC,
    MaxSplitRatio      NUMERIC
);

-- Table: I_ProcessesPerPeriod
CREATE TABLE I_ProcessesPerPeriod (
    ProcessId          VARCHAR,
    ProcessStep        VARCHAR,
    ItemId             VARCHAR,
    LocationId         VARCHAR,
    StartDate          VARDATE,
    UnitOperationTime  NUMERIC,
    Yield              NUMERIC DEFAULT 1,
    MinSplitRatio      NUMERIC,
    MaxSplitRatio      NUMERIC
);

-- Table: I_ResourceMaster
CREATE TABLE I_ResourceMaster (
    ResourceId            VARCHAR,
    ResourceDescription   VARCHAR,
    LocationId            VARCHAR,
    ResourceUOM           VARCHAR,
    SupplyCapacity        VARCHAR DEFAULT ('INF'),
    MinUtilization        NUMERIC DEFAULT (0),
    MaxUtilization        VARCHAR DEFAULT ('1'),
    ResourceStatus        INTEGER DEFAULT (1)
);

-- Table: I_ResourcePerPeriod
CREATE TABLE I_ResourcePerPeriod (
    ResourceId     VARCHAR,
    StartDate      VARDATE,
    SupplyCapacity VARCHAR,
    MinUtilization NUMERIC,
    MaxUtilization VARCHAR
);

-- Table: I_OpeningStocks
CREATE TABLE I_OpeningStocks (
    StockId      VARCHAR,
    ItemId       VARCHAR,
    LocationId   VARCHAR,
    Quantity     NUMERIC,
    EntryDate    VARDATE,
    ExpiryDate   VARDATE DEFAULT (72686) 
);

-- Table: I_TransportationPolicy
CREATE TABLE I_TransportationPolicy (
    ItemId                  VARCHAR,
    FromLocationId          VARCHAR,
    ToLocationId            VARCHAR,
    ModeId                  VARCHAR,
    UnitTransportationCost  NUMERIC,
    TransportationLeadTime  NUMERIC,
    MinQuantity             NUMERIC,
    MaxQuantity             NUMERIC,
    MinSplitRatio           NUMERIC,
    MaxSplitRatio           NUMERIC 
);

-- Table: I_TransportationPolicyPerPeriod
CREATE TABLE I_TransportationPolicyPerPeriod (
    ItemId                  VARCHAR,
    FromLocationId          VARCHAR,
    ToLocationId            VARCHAR,
    ModeId                  VARCHAR,
    StartDate               VARDATE,
    MinQuantity             NUMERIC DEFAULT (0),
    MaxQuantity             VARCHAR DEFAULT ('INF'),
    MinSplitRatio           NUMERIC,
    MaxSplitRatio           NUMERIC 
);

-- Table: I_ForecastRegistration
CREATE TABLE I_ForecastRegistration (
    ForecastItemId       VARCHAR,
    ItemId               VARCHAR,
    LocationId		     VARCHAR,
    StartDate			 VARDATE,
    EndDate			     VARDATE
);

CREATE TABLE O_ModelValidation (
    TableName       VARCHAR,
    ColumnName     VARCHAR,
    ColumnValue     VARCHAR,
    ErrorType       VARCHAR,
    ErrorMsg        VARCHAR
);

CREATE TABLE O_Transportation (
    ItemId                  VARCHAR,
    FromLocationId          VARCHAR,
    ToLocationId            VARCHAR,
    StartDate               VARDATE,
    EndDate                 VARDATE,
    ModeId                  VARCHAR,
    FlowQuantity            NUMERIC,
    FlowTransportationCost  NUMERIC
);

CREATE TABLE O_Inventory (
    ItemId                  VARCHAR,
    LocationId              VARCHAR,
    StartDate               VARDATE,
    OpeningInventory        NUMERIC,
    IncomingStock           NUMERIC,
    EndingInventory         NUMERIC,
    InTransitInventory      NUMERIC,
    InReleaseInventory      NUMERIC,
    ShortFallInventory      NUMERIC,
    InboundStock            NUMERIC,
    OutboundStock           NUMERIC,
    ProductionQuantity      NUMERIC,
    OrderedQuantity         NUMERIC,
    ConsumedQuantity        NUMERIC,
    ExpiredQuanity          NUMERIC,
    SatisfiedDemand         NUMERIC,
    Demand                  NUMERIC,
    RegistrationOutbound    NUMERIC,
    RegistrationInbound     NUMERIC,
    RequiredInventory       NUMERIC
);

CREATE TABLE O_InitialInventory (
    ItemId                  VARCHAR,
    LocationId              VARCHAR,
    Quantity                NUMERIC
);

CREATE TABLE O_Production (
    ItemId                 VARCHAR,
    LocationId             VARCHAR,
    ProcessId              VARCHAR,
    StartDate              VARDATE,
    ProductionQuantity     NUMERIC,
    ProductionCost         NUMERIC
);

CREATE TABLE O_ForecastRegistration (
    ItemId                 VARCHAR,
    LocationId             VARCHAR,
    StartDate              VARDATE,
    ForecastItemId         VARCHAR,
    SatisfiedQuantity      NUMERIC
);

CREATE TABLE O_Objective (
    SolveStatus            VARCHAR,
    ObjectiveName          VARCHAR,
    ObjectiveValue         NUMERIC,
    LastUpdateDate         VARDATE DEFAULT (datetime('now', 'localtime') )
);

CREATE TABLE O_DemandAnalysis (
    ItemId                 VARCHAR,
    LocationId             VARCHAR,
    FulFilledQuantity      NUMERIC,
    Quantity               NUMERIC,
    Iteration              INTEGER
);

CREATE TABLE O_Period (
    PeriodIdx              INTEGER,
    PeriodStart            VARDATE,
    PeriodEnd              VARDATE,
    PeriodMonth            VARCHAR,
    PeriodQuarter          VARCHAR,
    PeriodYear             VARCHAR,
    PeriodDays             NUMERIC
);


INSERT INTO S_TableGroup (GroupName, TableName, TableDisplayName, TableType, ColumnOrder, Table_Status, Freeze_Col_Num) VALUES ('Input Tables', 'I_ItemMaster', 'Items', 'Input', NULL, 'Active', NULL);
INSERT INTO S_TableGroup (GroupName, TableName, TableDisplayName, TableType, ColumnOrder, Table_Status, Freeze_Col_Num) VALUES ('Input Tables', 'I_LocationMaster', 'Locations', 'Input', NULL, 'Active', NULL);
INSERT INTO S_TableGroup (GroupName, TableName, TableDisplayName, TableType, ColumnOrder, Table_Status, Freeze_Col_Num) VALUES ('Input Tables', 'I_InventoryPolicy', 'Inventory Policy', 'Input', NULL, 'Active', NULL);
INSERT INTO S_TableGroup (GroupName, TableName, TableDisplayName, TableType, ColumnOrder, Table_Status, Freeze_Col_Num) VALUES ('Input Tables', 'I_ModelSetup', 'Model Setup', 'Input', NULL, 'Active', NULL);
INSERT INTO S_TableGroup (GroupName, TableName, TableDisplayName, TableType, ColumnOrder, Table_Status, Freeze_Col_Num) VALUES ('Input Tables', 'I_ForecastOrders', 'Forecasts', 'Input', NULL, 'Active', NULL);
INSERT INTO S_TableGroup (GroupName, TableName, TableDisplayName, TableType, ColumnOrder, Table_Status, Freeze_Col_Num) VALUES ('Input Tables', 'I_Processes', 'Operation Processes', 'Input', NULL, 'Active', NULL);
INSERT INTO S_TableGroup (GroupName, TableName, TableDisplayName, TableType, ColumnOrder, Table_Status, Freeze_Col_Num) VALUES ('Input Tables', 'I_BOMRecipe', 'Bill Of Materials', 'Input', NULL, 'Active', NULL);
INSERT INTO S_TableGroup (GroupName, TableName, TableDisplayName, TableType, ColumnOrder, Table_Status, Freeze_Col_Num) VALUES ('Input Tables', 'I_ResourceMaster', 'Resource', 'Input', NULL, 'Active', NULL);
INSERT INTO S_TableGroup (GroupName, TableName, TableDisplayName, TableType, ColumnOrder, Table_Status, Freeze_Col_Num) VALUES ('Input Tables', 'I_OpeningStocks', 'Opening Stocks', 'Input', NULL, 'Active', NULL);
INSERT INTO S_TableGroup (GroupName, TableName, TableDisplayName, TableType, ColumnOrder, Table_Status, Freeze_Col_Num) VALUES ('Input Tables', 'I_TransportationPolicy', 'Transportation', 'Input', NULL, 'Active', NULL);
INSERT INTO S_TableGroup (GroupName, TableName, TableDisplayName, TableType, ColumnOrder, Table_Status, Freeze_Col_Num) VALUES ('Input Tables', 'I_ForecastRegistration', 'Registration Calendar', 'Input', NULL, 'Active', NULL);

INSERT INTO S_TableGroup (GroupName, TableName, TableDisplayName, TableType, ColumnOrder, Table_Status, Freeze_Col_Num) VALUES ('Multiperiod Tables', 'I_InventoryPolicyPerPeriod', 'Inv Policy - Period', 'Input', NULL, 'Active', NULL);
INSERT INTO S_TableGroup (GroupName, TableName, TableDisplayName, TableType, ColumnOrder, Table_Status, Freeze_Col_Num) VALUES ('Multiperiod Tables', 'I_ProcessesPerPeriod', 'Operation Processes - Period', 'Input', NULL, 'Active', NULL);
INSERT INTO S_TableGroup (GroupName, TableName, TableDisplayName, TableType, ColumnOrder, Table_Status, Freeze_Col_Num) VALUES ('Multiperiod Tables', 'I_TransportationPolicyPerPeriod', 'Transportation Policy - Period', 'Input', NULL, 'Active', NULL);
INSERT INTO S_TableGroup (GroupName, TableName, TableDisplayName, TableType, ColumnOrder, Table_Status, Freeze_Col_Num) VALUES ('Multiperiod Tables', 'I_ResourcePerPeriod', 'Resource - Period', 'Input', NULL, 'Active', NULL);


INSERT INTO S_TableGroup (GroupName, TableName, TableDisplayName, TableType, ColumnOrder, Table_Status, Freeze_Col_Num) VALUES ('Output Tables', 'O_ModelValidation', 'Validation Output', 'Output', NULL, 'Active', NULL);
INSERT INTO S_TableGroup (GroupName, TableName, TableDisplayName, TableType, ColumnOrder, Table_Status, Freeze_Col_Num) VALUES ('Output Tables', 'O_Period', 'Periods', 'Output', NULL, 'Active', NULL);
INSERT INTO S_TableGroup (GroupName, TableName, TableDisplayName, TableType, ColumnOrder, Table_Status, Freeze_Col_Num) VALUES ('Output Tables', 'O_Inventory', 'Inventory Ouput', 'Output', NULL, 'Active', NULL);
INSERT INTO S_TableGroup (GroupName, TableName, TableDisplayName, TableType, ColumnOrder, Table_Status, Freeze_Col_Num) VALUES ('Output Tables', 'O_Transportation', 'Transportation Output', 'Output', NULL, 'Active', NULL);
INSERT INTO S_TableGroup (GroupName, TableName, TableDisplayName, TableType, ColumnOrder, Table_Status, Freeze_Col_Num) VALUES ('Output Tables', 'O_Production', 'Production Output', 'Output', NULL, 'Active', NULL);
INSERT INTO S_TableGroup (GroupName, TableName, TableDisplayName, TableType, ColumnOrder, Table_Status, Freeze_Col_Num) VALUES ('Output Tables', 'O_Objective', 'Objective Output', 'Output', NULL, 'Active', NULL);
INSERT INTO S_TableGroup (GroupName, TableName, TableDisplayName, TableType, ColumnOrder, Table_Status, Freeze_Col_Num) VALUES ('Output Tables', 'O_ForecastRegistration', 'Forecast Registration', 'Output', NULL, 'Active', NULL);
INSERT INTO S_TableGroup (GroupName, TableName, TableDisplayName, TableType, ColumnOrder, Table_Status, Freeze_Col_Num) VALUES ('Output Tables', 'O_DemandAnalysis', 'Demand Analysis', 'Output', NULL, 'Active', NULL);

INSERT INTO S_TableGroup (GroupName, TableName, TableDisplayName, TableType, ColumnOrder, Table_Status, Freeze_Col_Num) VALUES ('Log Tables', 'T_TaskLogs', 'Task Logs', 'Task Logs', NULL, 'Active', NULL);
INSERT INTO S_TableGroup (GroupName, TableName, TableDisplayName, TableType, ColumnOrder, Table_Status, Freeze_Col_Num) VALUES ('Log Tables', 'T_SolverLog', 'Solver Logs', 'Solver Logs', NULL, 'Active', NULL);

INSERT INTO S_TaskMaster (TaskId, TaskName, TaskDisplayName, TaskType) VALUES (1, 'validate_model.py', 'Validate Model', 'PythonScript');
INSERT INTO S_TaskMaster (TaskId, TaskName, TaskDisplayName, TaskType) VALUES (2, 'clean_model.py', 'Clean Model', 'PythonScript');
INSERT INTO S_TaskMaster (TaskId, TaskName, TaskDisplayName, TaskType) VALUES (3, 'optimize.py', 'Optimize', 'PythonScript');
INSERT INTO S_TaskMaster (TaskId, TaskName, TaskDisplayName, TaskType) VALUES (4, 'propagate_demand.py', 'Propagate Demand', 'PythonScript');


INSERT INTO I_BOMRecipe (BOMId, ItemId, LocationId, UsageQuantity) VALUES ('BOM_FG_1_MFG_IM1', 'IM_A', 'MFG_IM1', 1);
INSERT INTO I_BOMRecipe (BOMId, ItemId, LocationId, UsageQuantity) VALUES ('BOM_FG_1_MFG_IM2', 'IM_A', 'MFG_IM2', 1);
INSERT INTO I_BOMRecipe (BOMId, ItemId, LocationId, UsageQuantity) VALUES ('BOM_IM_A_MFG_IM1', 'API_X', 'MFG_IM1', 1);
INSERT INTO I_BOMRecipe (BOMId, ItemId, LocationId, UsageQuantity) VALUES ('BOM_IM_A_MFG_IM2', 'API_X', 'MFG_IM2', 1);

INSERT INTO I_ForecastOrders (OrderId, ItemId, LocationId, ForecastArrivalDate, Quantity, SalesPrice) VALUES ('ORDER_079', 'FG_1', 'CustomerA', '2024-01-01', 73, 100);
INSERT INTO I_ForecastOrders (OrderId, ItemId, LocationId, ForecastArrivalDate, Quantity, SalesPrice) VALUES ('ORDER_080', 'FG_1', 'CustomerA', '2024-02-01', 42, 100);
INSERT INTO I_ForecastOrders (OrderId, ItemId, LocationId, ForecastArrivalDate, Quantity, SalesPrice) VALUES ('ORDER_081', 'FG_1', 'CustomerA', '2024-03-01', 68, 100);
INSERT INTO I_ForecastOrders (OrderId, ItemId, LocationId, ForecastArrivalDate, Quantity, SalesPrice) VALUES ('ORDER_082', 'FG_1', 'CustomerA', '2024-04-01', 27, 100);
INSERT INTO I_ForecastOrders (OrderId, ItemId, LocationId, ForecastArrivalDate, Quantity, SalesPrice) VALUES ('ORDER_083', 'FG_1', 'CustomerA', '2024-05-01', 95, 100);
INSERT INTO I_ForecastOrders (OrderId, ItemId, LocationId, ForecastArrivalDate, Quantity, SalesPrice) VALUES ('ORDER_084', 'FG_1', 'CustomerA', '2024-06-01', 52, 100);
INSERT INTO I_ForecastOrders (OrderId, ItemId, LocationId, ForecastArrivalDate, Quantity, SalesPrice) VALUES ('ORDER_085', 'FG_1', 'CustomerA', '2024-07-01', 33, 100);
INSERT INTO I_ForecastOrders (OrderId, ItemId, LocationId, ForecastArrivalDate, Quantity, SalesPrice) VALUES ('ORDER_086', 'FG_1', 'CustomerA', '2024-08-01', 85, 100);
INSERT INTO I_ForecastOrders (OrderId, ItemId, LocationId, ForecastArrivalDate, Quantity, SalesPrice) VALUES ('ORDER_087', 'FG_1', 'CustomerA', '2024-09-01', 61, 100);
INSERT INTO I_ForecastOrders (OrderId, ItemId, LocationId, ForecastArrivalDate, Quantity, SalesPrice) VALUES ('ORDER_088', 'FG_1', 'CustomerA', '2024-10-01', 17, 100);
INSERT INTO I_ForecastOrders (OrderId, ItemId, LocationId, ForecastArrivalDate, Quantity, SalesPrice) VALUES ('ORDER_089', 'FG_1', 'CustomerA', '2024-11-01', 94, 100);
INSERT INTO I_ForecastOrders (OrderId, ItemId, LocationId, ForecastArrivalDate, Quantity, SalesPrice) VALUES ('ORDER_090', 'FG_1', 'CustomerA', '2024-12-01', 78, 100);
INSERT INTO I_ForecastOrders (OrderId, ItemId, LocationId, ForecastArrivalDate, Quantity, SalesPrice) VALUES ('ORDER_091', 'FG_1', 'CustomerA', '2025-01-01', 36, 100);
INSERT INTO I_ForecastOrders (OrderId, ItemId, LocationId, ForecastArrivalDate, Quantity, SalesPrice) VALUES ('ORDER_092', 'FG_1', 'CustomerA', '2025-02-01', 69, 100);
INSERT INTO I_ForecastOrders (OrderId, ItemId, LocationId, ForecastArrivalDate, Quantity, SalesPrice) VALUES ('ORDER_093', 'FG_1', 'CustomerA', '2025-03-01', 23, 100);
INSERT INTO I_ForecastOrders (OrderId, ItemId, LocationId, ForecastArrivalDate, Quantity, SalesPrice) VALUES ('ORDER_094', 'FG_1', 'CustomerA', '2025-04-01', 42, 100);
INSERT INTO I_ForecastOrders (OrderId, ItemId, LocationId, ForecastArrivalDate, Quantity, SalesPrice) VALUES ('ORDER_095', 'FG_1', 'CustomerA', '2025-05-01', 87, 100);
INSERT INTO I_ForecastOrders (OrderId, ItemId, LocationId, ForecastArrivalDate, Quantity, SalesPrice) VALUES ('ORDER_096', 'FG_1', 'CustomerA', '2025-06-01', 57, 100);
INSERT INTO I_ForecastOrders (OrderId, ItemId, LocationId, ForecastArrivalDate, Quantity, SalesPrice) VALUES ('ORDER_097', 'FG_1', 'CustomerA', '2025-07-01', 13, 100);
INSERT INTO I_ForecastOrders (OrderId, ItemId, LocationId, ForecastArrivalDate, Quantity, SalesPrice) VALUES ('ORDER_098', 'FG_1', 'CustomerA', '2025-08-01', 81, 100);
INSERT INTO I_ForecastOrders (OrderId, ItemId, LocationId, ForecastArrivalDate, Quantity, SalesPrice) VALUES ('ORDER_099', 'FG_1', 'CustomerA', '2025-09-01', 45, 100);
INSERT INTO I_ForecastOrders (OrderId, ItemId, LocationId, ForecastArrivalDate, Quantity, SalesPrice) VALUES ('ORDER_100', 'FG_1', 'CustomerA', '2025-10-01', 29, 100);
INSERT INTO I_ForecastOrders (OrderId, ItemId, LocationId, ForecastArrivalDate, Quantity, SalesPrice) VALUES ('ORDER_101', 'FG_1', 'CustomerA', '2025-11-01', 76, 100);
INSERT INTO I_ForecastOrders (OrderId, ItemId, LocationId, ForecastArrivalDate, Quantity, SalesPrice) VALUES ('ORDER_102', 'FG_1', 'CustomerA', '2025-12-01', 39, 100);
INSERT INTO I_ForecastOrders (OrderId, ItemId, LocationId, ForecastArrivalDate, Quantity, SalesPrice) VALUES ('ORDER_103', 'FG_1', 'CustomerB', '2024-01-01', 62, 100);
INSERT INTO I_ForecastOrders (OrderId, ItemId, LocationId, ForecastArrivalDate, Quantity, SalesPrice) VALUES ('ORDER_104', 'FG_1', 'CustomerB', '2024-02-01', 21, 100);
INSERT INTO I_ForecastOrders (OrderId, ItemId, LocationId, ForecastArrivalDate, Quantity, SalesPrice) VALUES ('ORDER_105', 'FG_1', 'CustomerB', '2024-03-01', 95, 100);
INSERT INTO I_ForecastOrders (OrderId, ItemId, LocationId, ForecastArrivalDate, Quantity, SalesPrice) VALUES ('ORDER_106', 'FG_1', 'CustomerB', '2024-04-01', 54, 100);
INSERT INTO I_ForecastOrders (OrderId, ItemId, LocationId, ForecastArrivalDate, Quantity, SalesPrice) VALUES ('ORDER_107', 'FG_1', 'CustomerB', '2024-05-01', 36, 100);
INSERT INTO I_ForecastOrders (OrderId, ItemId, LocationId, ForecastArrivalDate, Quantity, SalesPrice) VALUES ('ORDER_108', 'FG_1', 'CustomerB', '2024-06-01', 73, 100);
INSERT INTO I_ForecastOrders (OrderId, ItemId, LocationId, ForecastArrivalDate, Quantity, SalesPrice) VALUES ('ORDER_109', 'FG_1', 'CustomerB', '2024-07-01', 47, 100);
INSERT INTO I_ForecastOrders (OrderId, ItemId, LocationId, ForecastArrivalDate, Quantity, SalesPrice) VALUES ('ORDER_110', 'FG_1', 'CustomerB', '2024-08-01', 18, 100);
INSERT INTO I_ForecastOrders (OrderId, ItemId, LocationId, ForecastArrivalDate, Quantity, SalesPrice) VALUES ('ORDER_111', 'FG_1', 'CustomerB', '2024-09-01', 86, 100);
INSERT INTO I_ForecastOrders (OrderId, ItemId, LocationId, ForecastArrivalDate, Quantity, SalesPrice) VALUES ('ORDER_112', 'FG_1', 'CustomerB', '2024-10-01', 38, 100);
INSERT INTO I_ForecastOrders (OrderId, ItemId, LocationId, ForecastArrivalDate, Quantity, SalesPrice) VALUES ('ORDER_113', 'FG_1', 'CustomerB', '2024-11-01', 69, 100);
INSERT INTO I_ForecastOrders (OrderId, ItemId, LocationId, ForecastArrivalDate, Quantity, SalesPrice) VALUES ('ORDER_114', 'FG_1', 'CustomerB', '2024-12-01', 32, 100);
INSERT INTO I_ForecastOrders (OrderId, ItemId, LocationId, ForecastArrivalDate, Quantity, SalesPrice) VALUES ('ORDER_115', 'FG_1', 'CustomerB', '2025-01-01', 79, 100);
INSERT INTO I_ForecastOrders (OrderId, ItemId, LocationId, ForecastArrivalDate, Quantity, SalesPrice) VALUES ('ORDER_116', 'FG_1', 'CustomerB', '2025-02-01', 43, 100);
INSERT INTO I_ForecastOrders (OrderId, ItemId, LocationId, ForecastArrivalDate, Quantity, SalesPrice) VALUES ('ORDER_117', 'FG_1', 'CustomerB', '2025-03-01', 83, 100);
INSERT INTO I_ForecastOrders (OrderId, ItemId, LocationId, ForecastArrivalDate, Quantity, SalesPrice) VALUES ('ORDER_118', 'FG_1', 'CustomerB', '2025-04-01', 56, 100);
INSERT INTO I_ForecastOrders (OrderId, ItemId, LocationId, ForecastArrivalDate, Quantity, SalesPrice) VALUES ('ORDER_119', 'FG_1', 'CustomerB', '2025-05-01', 88, 100);
INSERT INTO I_ForecastOrders (OrderId, ItemId, LocationId, ForecastArrivalDate, Quantity, SalesPrice) VALUES ('ORDER_120', 'FG_1', 'CustomerB', '2025-06-01', 49, 100);
INSERT INTO I_ForecastOrders (OrderId, ItemId, LocationId, ForecastArrivalDate, Quantity, SalesPrice) VALUES ('ORDER_121', 'FG_1', 'CustomerB', '2025-07-01', 59, 100);
INSERT INTO I_ForecastOrders (OrderId, ItemId, LocationId, ForecastArrivalDate, Quantity, SalesPrice) VALUES ('ORDER_122', 'FG_1', 'CustomerB', '2025-08-01', 43, 100);
INSERT INTO I_ForecastOrders (OrderId, ItemId, LocationId, ForecastArrivalDate, Quantity, SalesPrice) VALUES ('ORDER_123', 'FG_1', 'CustomerB', '2025-09-01', 73, 100);
INSERT INTO I_ForecastOrders (OrderId, ItemId, LocationId, ForecastArrivalDate, Quantity, SalesPrice) VALUES ('ORDER_124', 'FG_1', 'CustomerB', '2025-10-01', 81, 100);
INSERT INTO I_ForecastOrders (OrderId, ItemId, LocationId, ForecastArrivalDate, Quantity, SalesPrice) VALUES ('ORDER_125', 'FG_1', 'CustomerB', '2025-11-01', 72, 100);
INSERT INTO I_ForecastOrders (OrderId, ItemId, LocationId, ForecastArrivalDate, Quantity, SalesPrice) VALUES ('ORDER_126', 'FG_1', 'CustomerB', '2025-12-01', 43, 100);


INSERT INTO I_InventoryPolicy (ItemId, LocationId, InventoryType, IsProduction, IsStorage, InventoryUnitCost, InventoryHoldingCost, SalesPrice, SafetyStockDOS, DOSWindow, InventoryShelfLife, MinReleaseTime, MinEndingInventory, MaxEndingInventory, MinProductionQuantity, MaxProductionQuantity, InventoryStatus) VALUES ('FG_1', 'CustomerA', 'Customer', 0, 1, 50, NULL, 100, 0, 0, NULL, NULL, 0, 'INF', 0, 'INF', 1);
INSERT INTO I_InventoryPolicy (ItemId, LocationId, InventoryType, IsProduction, IsStorage, InventoryUnitCost, InventoryHoldingCost, SalesPrice, SafetyStockDOS, DOSWindow, InventoryShelfLife, MinReleaseTime, MinEndingInventory, MaxEndingInventory, MinProductionQuantity, MaxProductionQuantity, InventoryStatus) VALUES ('FG_1', 'CustomerB', 'Customer', 0, 1, 50, NULL, 100, 0, 0, NULL, NULL, 0, 'INF', 0, 'INF', 1);
INSERT INTO I_InventoryPolicy (ItemId, LocationId, InventoryType, IsProduction, IsStorage, InventoryUnitCost, InventoryHoldingCost, SalesPrice, SafetyStockDOS, DOSWindow, InventoryShelfLife, MinReleaseTime, MinEndingInventory, MaxEndingInventory, MinProductionQuantity, MaxProductionQuantity, InventoryStatus) VALUES ('FG_1', 'MFG_IM1', 'Plant', 1, 0, 50, NULL, 100, 0, 0, NULL, NULL, 0, 'INF', 0, 'INF', 1);
INSERT INTO I_InventoryPolicy (ItemId, LocationId, InventoryType, IsProduction, IsStorage, InventoryUnitCost, InventoryHoldingCost, SalesPrice, SafetyStockDOS, DOSWindow, InventoryShelfLife, MinReleaseTime, MinEndingInventory, MaxEndingInventory, MinProductionQuantity, MaxProductionQuantity, InventoryStatus) VALUES ('FG_1', 'MFG_IM2', 'Plant', 1, 0, 50, NULL, 100, 0, 0, NULL, NULL, 0, 'INF', 0, 'INF', 1);
INSERT INTO I_InventoryPolicy (ItemId, LocationId, InventoryType, IsProduction, IsStorage, InventoryUnitCost, InventoryHoldingCost, SalesPrice, SafetyStockDOS, DOSWindow, InventoryShelfLife, MinReleaseTime, MinEndingInventory, MaxEndingInventory, MinProductionQuantity, MaxProductionQuantity, InventoryStatus) VALUES ('IM_A', 'MFG_IM1', 'Plant', 1, 1, 20, NULL, NULL, 0, 0, NULL, NULL, 0, 'INF', 0, 'INF', 1);
INSERT INTO I_InventoryPolicy (ItemId, LocationId, InventoryType, IsProduction, IsStorage, InventoryUnitCost, InventoryHoldingCost, SalesPrice, SafetyStockDOS, DOSWindow, InventoryShelfLife, MinReleaseTime, MinEndingInventory, MaxEndingInventory, MinProductionQuantity, MaxProductionQuantity, InventoryStatus) VALUES ('IM_A', 'MFG_IM2', 'Plant', 1, 1, 20, NULL, NULL, 0, 0, NULL, NULL, 0, 'INF', 0, 'INF', 1);
INSERT INTO I_InventoryPolicy (ItemId, LocationId, InventoryType, IsProduction, IsStorage, InventoryUnitCost, InventoryHoldingCost, SalesPrice, SafetyStockDOS, DOSWindow, InventoryShelfLife, MinReleaseTime, MinEndingInventory, MaxEndingInventory, MinProductionQuantity, MaxProductionQuantity, InventoryStatus) VALUES ('API_X', 'MFG_IM1', 'ProductLocation', 0, 1, 5, NULL, NULL, 0, 0, NULL, NULL, 0, 'INF', 0, 'INF', 1);
INSERT INTO I_InventoryPolicy (ItemId, LocationId, InventoryType, IsProduction, IsStorage, InventoryUnitCost, InventoryHoldingCost, SalesPrice, SafetyStockDOS, DOSWindow, InventoryShelfLife, MinReleaseTime, MinEndingInventory, MaxEndingInventory, MinProductionQuantity, MaxProductionQuantity, InventoryStatus) VALUES ('API_X', 'MFG_IM2', 'ProductLocation', 0, 1, 5, NULL, NULL, 0, 0, NULL, NULL, 0, 'INF', 0, 'INF', 1);
INSERT INTO I_InventoryPolicy (ItemId, LocationId, InventoryType, IsProduction, IsStorage, InventoryUnitCost, InventoryHoldingCost, SalesPrice, SafetyStockDOS, DOSWindow, InventoryShelfLife, MinReleaseTime, MinEndingInventory, MaxEndingInventory, MinProductionQuantity, MaxProductionQuantity, InventoryStatus) VALUES ('API_X', 'MFG_API', 'Plant', 1, 0, 5, NULL, NULL, 0, 0, NULL, NULL, 0, 'INF', 0, 'INF', 1);

INSERT INTO I_ItemMaster (ItemId, ItemDescription, ItemType, SalesPrice, UnitCost, Brand, SubBrand, Category, SubCategory, ItemStatus) VALUES ('FG_1', 'Finshed Goods', 'FG', 100, 50, NULL, NULL, NULL, NULL, 1);
INSERT INTO I_ItemMaster (ItemId, ItemDescription, ItemType, SalesPrice, UnitCost, Brand, SubBrand, Category, SubCategory, ItemStatus) VALUES ('IM_A', 'Intermediate Product', 'IM', NULL, 20, NULL, NULL, NULL, NULL, 1);
INSERT INTO I_ItemMaster (ItemId, ItemDescription, ItemType, SalesPrice, UnitCost, Brand, SubBrand, Category, SubCategory, ItemStatus) VALUES ('API_X', 'API', 'API', NULL, 5, NULL, NULL, NULL, NULL, 1);

INSERT INTO I_LocationMaster (LocationId, LocationType, LocationCategory, LocationAttribute1, LocationAttribute2, Region, Country, State, City, ZipCode, Longitude, Latitude) VALUES ('CustomerA', 'Customer', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL);
INSERT INTO I_LocationMaster (LocationId, LocationType, LocationCategory, LocationAttribute1, LocationAttribute2, Region, Country, State, City, ZipCode, Longitude, Latitude) VALUES ('CustomerB', 'Customer', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL);
INSERT INTO I_LocationMaster (LocationId, LocationType, LocationCategory, LocationAttribute1, LocationAttribute2, Region, Country, State, City, ZipCode, Longitude, Latitude) VALUES ('MFG_API', 'Facility', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL);
INSERT INTO I_LocationMaster (LocationId, LocationType, LocationCategory, LocationAttribute1, LocationAttribute2, Region, Country, State, City, ZipCode, Longitude, Latitude) VALUES ('MFG_IM1', 'Facility', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL);
INSERT INTO I_LocationMaster (LocationId, LocationType, LocationCategory, LocationAttribute1, LocationAttribute2, Region, Country, State, City, ZipCode, Longitude, Latitude) VALUES ('MFG_IM2', 'Facility', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL);

INSERT INTO I_ModelSetup (ModelName, StartDate, TimeFrequency, NumberOfPeriods, InterestRate, DOSWindowStartPeriod) VALUES ('SCL Test Model', '2024-01-01', 'Monthly', 24, 0.01, 1);

INSERT INTO I_OpeningStocks (StockId, ItemId, LocationId, Quantity, EntryDate, ExpiryDate) VALUES ('STOCK_001', 'FG_1', 'CustomerA', 11, '2024-01-01', '2099-01-01');
INSERT INTO I_OpeningStocks (StockId, ItemId, LocationId, Quantity, EntryDate, ExpiryDate) VALUES ('STOCK_002', 'FG_1', 'CustomerB', 23, '2024-01-01', '2099-01-01');
INSERT INTO I_OpeningStocks (StockId, ItemId, LocationId, Quantity, EntryDate, ExpiryDate) VALUES ('STOCK_003', 'IM_A', 'MFG_IM1', 22, '2024-01-01', '2099-01-01');
INSERT INTO I_OpeningStocks (StockId, ItemId, LocationId, Quantity, EntryDate, ExpiryDate) VALUES ('STOCK_004', 'IM_A', 'MFG_IM2', 15, '2024-01-01', '2099-01-01');
INSERT INTO I_OpeningStocks (StockId, ItemId, LocationId, Quantity, EntryDate, ExpiryDate) VALUES ('STOCK_005', 'API_X', 'MFG_IM1', 18, '2024-01-01', '2099-01-01');
INSERT INTO I_OpeningStocks (StockId, ItemId, LocationId, Quantity, EntryDate, ExpiryDate) VALUES ('STOCK_006', 'API_X', 'MFG_IM2', 10, '2024-01-01', '2099-01-01');

INSERT INTO I_Processes (ProcessId, ProcessStep, ItemId, LocationId, BOMId, ResourceId, UnitOperationTime, UnitOperationCost, Yield, MOQ, PersonnelTime, LotSizeRounding, MinSplitRatio, MaxSplitRatio) VALUES ('PR_FG_1_MFG_IM1', '0', 'FG_1', 'MFG_IM1', 'BOM_FG_1_MFG_IM1', 'RS_MFG_IM1', 1, NULL, 1, NULL, NULL, NULL, NULL, NULL);
INSERT INTO I_Processes (ProcessId, ProcessStep, ItemId, LocationId, BOMId, ResourceId, UnitOperationTime, UnitOperationCost, Yield, MOQ, PersonnelTime, LotSizeRounding, MinSplitRatio, MaxSplitRatio) VALUES ('PR_FG_1_MFG_IM2', '0', 'FG_1', 'MFG_IM2', 'BOM_FG_1_MFG_IM2', 'RS_MFG_IM2', 1, NULL, 1, NULL, NULL, NULL, NULL, NULL);
INSERT INTO I_Processes (ProcessId, ProcessStep, ItemId, LocationId, BOMId, ResourceId, UnitOperationTime, UnitOperationCost, Yield, MOQ, PersonnelTime, LotSizeRounding, MinSplitRatio, MaxSplitRatio) VALUES ('PR_IM_A_MFG_IM1', '0', 'IM_A', 'MFG_IM1', 'BOM_IM_A_MFG_IM1', 'RS_MFG_IM1', 1, NULL, 1, NULL, NULL, NULL, NULL, NULL);
INSERT INTO I_Processes (ProcessId, ProcessStep, ItemId, LocationId, BOMId, ResourceId, UnitOperationTime, UnitOperationCost, Yield, MOQ, PersonnelTime, LotSizeRounding, MinSplitRatio, MaxSplitRatio) VALUES ('PR_IM_A_MFG_IM2', '0', 'IM_A', 'MFG_IM2', 'BOM_IM_A_MFG_IM2', 'RS_MFG_IM2', 1, NULL, 1, NULL, NULL, NULL, NULL, NULL);
INSERT INTO I_Processes (ProcessId, ProcessStep, ItemId, LocationId, BOMId, ResourceId, UnitOperationTime, UnitOperationCost, Yield, MOQ, PersonnelTime, LotSizeRounding, MinSplitRatio, MaxSplitRatio) VALUES ('PR_API_X_MFG_API', '0', 'API_X', 'MFG_API', NULL, 'RS_MFG_API', 1, NULL, 1, NULL, NULL, NULL, NULL, NULL);

INSERT INTO I_ResourceMaster (ResourceId, ResourceDescription, LocationId, ResourceUOM, SupplyCapacity, MinUtilization, MaxUtilization, ResourceStatus) VALUES ('RS_MFG_IM1', 'RS_MFG_IM1', 'MFG_IM1', 'HRS', 'INF', 0, '1', 1);
INSERT INTO I_ResourceMaster (ResourceId, ResourceDescription, LocationId, ResourceUOM, SupplyCapacity, MinUtilization, MaxUtilization, ResourceStatus) VALUES ('RS_MFG_IM2', 'RS_MFG_IM2', 'MFG_IM2', 'HRS', 'INF', 0, '1', 1);
INSERT INTO I_ResourceMaster (ResourceId, ResourceDescription, LocationId, ResourceUOM, SupplyCapacity, MinUtilization, MaxUtilization, ResourceStatus) VALUES ('RS_MFG_API', 'RS_MFG_API', 'MFG_API', 'HRS', 'INF', 0, '1', 1);

INSERT INTO I_TransportationPolicy (ItemId, FromLocationId, ToLocationId, ModeId, UnitTransportationCost, TransportationLeadTime, MinQuantity, MaxQuantity, MinSplitRatio, MaxSplitRatio) VALUES ('FG_1', 'MFG_IM1', 'CustomerA', 'Truck', 5, 30, NULL, NULL, NULL, NULL);
INSERT INTO I_TransportationPolicy (ItemId, FromLocationId, ToLocationId, ModeId, UnitTransportationCost, TransportationLeadTime, MinQuantity, MaxQuantity, MinSplitRatio, MaxSplitRatio) VALUES ('FG_1', 'MFG_IM1', 'CustomerB', 'Truck', 3, 60, NULL, NULL, NULL, NULL);
INSERT INTO I_TransportationPolicy (ItemId, FromLocationId, ToLocationId, ModeId, UnitTransportationCost, TransportationLeadTime, MinQuantity, MaxQuantity, MinSplitRatio, MaxSplitRatio) VALUES ('FG_1', 'MFG_IM2', 'CustomerA', 'Truck', 3, 60, NULL, NULL, NULL, NULL);
INSERT INTO I_TransportationPolicy (ItemId, FromLocationId, ToLocationId, ModeId, UnitTransportationCost, TransportationLeadTime, MinQuantity, MaxQuantity, MinSplitRatio, MaxSplitRatio) VALUES ('FG_1', 'MFG_IM2', 'CustomerB', 'Truck', 4, 30, NULL, NULL, NULL, NULL);
INSERT INTO I_TransportationPolicy (ItemId, FromLocationId, ToLocationId, ModeId, UnitTransportationCost, TransportationLeadTime, MinQuantity, MaxQuantity, MinSplitRatio, MaxSplitRatio) VALUES ('API_X', 'MFG_API', 'MFG_IM1', 'Truck', 5, 30, NULL, NULL, NULL, NULL);
INSERT INTO I_TransportationPolicy (ItemId, FromLocationId, ToLocationId, ModeId, UnitTransportationCost, TransportationLeadTime, MinQuantity, MaxQuantity, MinSplitRatio, MaxSplitRatio) VALUES ('API_X', 'MFG_API', 'MFG_IM2', 'Truck', 5, 30, NULL, NULL, NULL, NULL);


COMMIT TRANSACTION;