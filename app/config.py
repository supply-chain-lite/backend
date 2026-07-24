import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# JWT & cookie settings
SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise Exception("SECRET_KEY is not set in environment variables.")
ACCESS_TOKEN_EXPIRE_DAYS = int(os.getenv("ACCESS_TOKEN_EXPIRE_DAYS", 1))

# Password hashing pepper — kept separate from SECRET_KEY so JWT key rotation
# does not invalidate existing password hashes. Set this once and never change it.
# For existing deployments, set PASSWORD_PEPPER to the previous SECRET_KEY value.
PASSWORD_PEPPER = os.getenv("PASSWORD_PEPPER", "")
MAX_ATTEMPTS = int(os.getenv("MAX_ATTEMPTS", "5"))
LOCK_TIME_MINUTES = int(os.getenv("LOCK_TIME_MINUTES", "1"))
SMTP_URL = os.getenv("SMTP_URL")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PWD = os.getenv("SMTP_PWD")
master_db = os.getenv("SQLITE_DB_PATH")
BASE_URL = os.getenv("BASE_URL", "http://localhost:3000")
BROKER_URL = os.getenv("BROKER_URL", "redis://localhost:6379/0")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
S3_URL = os.getenv("S3_URL")
SETUP_S3 = int(os.getenv("SETUP_S3", "0"))
SQLITE_DIFF_TOOL = os.getenv("SQLITE_DIFF_TOOL", "sqldiff.exe")


if not master_db:
    raise Exception("SQLITE_DB_PATH is not set in environment variables.")
if not os.path.isfile(master_db):
    raise Exception(f"Database file not found at {master_db}. Please check the path and try again.")

_data_folder_env = os.getenv("DATA_FOLDER")
if not _data_folder_env:
    raise Exception("DATA_FOLDER is not set in environment variables.")
ROOT_DATA_FOLDER = Path(_data_folder_env)

MAX_BACKUPS = int(os.getenv("MAX_BACKUPS", 10))
TEMP_FOLDER = ROOT_DATA_FOLDER / "temp"
STATIC_FOLDER = ROOT_DATA_FOLDER / "static"
BACKUP_FOLDER = ROOT_DATA_FOLDER / "backup"
LOG_FOLDER = ROOT_DATA_FOLDER / "logs"
DATA_FOLDER = ROOT_DATA_FOLDER / "models"
CELERY_MODELS_FOLDER = ROOT_DATA_FOLDER / "task_models"
CELERY_LOG_FOLDER = ROOT_DATA_FOLDER / "task_logs"
CELERY_TEMP_FOLDER = ROOT_DATA_FOLDER / "task_temp"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
TASK_PROCESS_TIMEOUT_MINUTES = int(os.getenv("TASK_PROCESS_TIMEOUT_MINUTES", 120))

if not os.path.exists(DATA_FOLDER):
    os.makedirs(DATA_FOLDER, exist_ok=True)

if not os.path.exists(STATIC_FOLDER):
    os.makedirs(STATIC_FOLDER, exist_ok=True)

if not os.path.exists(BACKUP_FOLDER):
    os.makedirs(BACKUP_FOLDER, exist_ok=True)

if not os.path.exists(TEMP_FOLDER):
    os.makedirs(TEMP_FOLDER, exist_ok=True)

if not os.path.exists(LOG_FOLDER):
    os.makedirs(LOG_FOLDER, exist_ok=True)

if not os.path.exists(CELERY_MODELS_FOLDER):
    os.makedirs(CELERY_MODELS_FOLDER, exist_ok=True)

if not os.path.exists(CELERY_LOG_FOLDER):
    os.makedirs(CELERY_LOG_FOLDER, exist_ok=True)

if not os.path.exists(CELERY_TEMP_FOLDER):
    os.makedirs(CELERY_TEMP_FOLDER, exist_ok=True)
