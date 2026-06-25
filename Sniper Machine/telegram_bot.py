import requests
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

def send_telegram_alert(message: str):
    """Sends a formatted message to the configured Telegram chat."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram credentials missing in config.py")
        return False
        
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    
    try:
        response = requests.post(url, json=payload, timeout=5)
        if response.status_code == 200:
            print(f"[SUCCESS] Telegram Alert Sent: {message.splitlines()[0]}")
            return True
        else:
            print(f"[ERROR] Telegram Error: {response.text}")
            return False
    except Exception as e:
        print(f"[EXCEPTION] Telegram Exception: {e}")
        return False

if __name__ == "__main__":
    # Test message
    send_telegram_alert("[ALERT] Sniper Machine Initialized\nSystem is online and waiting for signals.")
