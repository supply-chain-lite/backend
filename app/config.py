import os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()

# JWT & cookie settings
SECRET_KEY = os.getenv("SECRET_KEY")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 600))
SECURE_COOKIES = os.getenv("SECURE_COOKIES", "True").lower() in ["true", "1", "yes"]
MAX_ATTEMPTS = int(os.getenv("MAX_ATTEMPTS", "5"))
LOCK_TIME_MINUTES = int(os.getenv("LOCK_TIME_MINUTES", "1"))
SMTP_URL = os.getenv("SMTP_URL")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PWD = os.getenv("SMTP_PWD")
master_db = os.getenv("DB_PATH")
DATA_FOLDER = Path(os.getenv("DATA_FOLDER"))
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
