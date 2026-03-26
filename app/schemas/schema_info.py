import os
from pathlib import Path

# folder_name = os.path.basename(os.path.dirname(os.path.abspath(__file__)))

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = os.path.join(PROJECT_ROOT, "SCHEMA")

schema_info = {
    "Supply Planning": {
        "with_data": os.path.join(SCHEMA_DIR, "supply_planning_with_data.sql"),
        "without_data": os.path.join(SCHEMA_DIR, "supply_planning.sql"),
    },
    "Generic Data Model": {
        "with_data": os.path.join(SCHEMA_DIR, "generic_data_model_with_data.sql"),
        "without_data": os.path.join(SCHEMA_DIR, "generic_data_model.sql"),
    },
}
