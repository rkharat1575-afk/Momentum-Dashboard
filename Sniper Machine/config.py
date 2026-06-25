import sys
import os

# Add parent directory to path so we can import the existing Sharekhan config and tokens
PARENT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(PARENT_DIR)

try:
    from config import API_KEY, SECRET_KEY
except ImportError:
    print("Warning: Could not import API_KEY and SECRET_KEY from parent config.py")
    API_KEY = "YOUR_API_KEY"
    SECRET_KEY = "YOUR_SECRET_KEY"

# Telegram Bot Credentials
# Helper to load .env manually if python-dotenv is not installed
if os.path.exists(".env"):
    with open(".env") as f:
        for line in f:
            if line.strip() and not line.strip().startswith("#") and "=" in line:
                key, val = line.strip().split("=", 1)
                os.environ[key.strip()] = val.strip()
elif os.path.exists("../.env"):
    with open("../.env") as f:
        for line in f:
            if line.strip() and not line.strip().startswith("#") and "=" in line:
                key, val = line.strip().split("=", 1)
                os.environ[key.strip()] = val.strip()

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# System Configuration
TARGET_POINTS = 10.0     # How many points we want to scalp
STOP_LOSS_POINTS = 5.0   # Stop loss in points
DELTA_TARGET_MIN = 0.50  # We want ATM/ITM options
DELTA_TARGET_MAX = 0.65
