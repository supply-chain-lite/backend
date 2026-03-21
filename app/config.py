import os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()

# JWT & cookie settings
SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise Exception("SECRET_KEY is not set in environment variables.")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 600))
MAX_ATTEMPTS = int(os.getenv("MAX_ATTEMPTS", "5"))
LOCK_TIME_MINUTES = int(os.getenv("LOCK_TIME_MINUTES", "1"))
SMTP_URL = os.getenv("SMTP_URL")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PWD = os.getenv("SMTP_PWD")
master_db = os.getenv("SQLITE_DB_PATH")

if not master_db:
    raise Exception("SQLITE_DB_PATH is not set in environment variables.")
if not os.path.isfile(master_db):
    raise Exception(f"Database file not found at {master_db}. Please check the path and try again.")

_data_folder_env = os.getenv("DATA_FOLDER")
if not _data_folder_env:
    raise Exception("DATA_FOLDER is not set in environment variables.")
DATA_FOLDER = Path(_data_folder_env)

MAX_BACKUPS = int(os.getenv("MAX_BACKUPS", 10))
TEMP_FOLDER = DATA_FOLDER / "temp"
BACKUP_FOLDER = DATA_FOLDER / "backup"
DATA_FOLDER = DATA_FOLDER / "models"

if not os.path.exists(DATA_FOLDER):
    os.makedirs(DATA_FOLDER)

if not os.path.exists(BACKUP_FOLDER):
    os.makedirs(BACKUP_FOLDER)

if not os.path.exists(TEMP_FOLDER):
    os.makedirs(TEMP_FOLDER)
