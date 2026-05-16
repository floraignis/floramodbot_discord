import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN: str = os.getenv("DISCORD_TOKEN", "")
CREATOR_ID: int = int(os.getenv("CREATOR_ID", 0))

MOD_ROLE_NAME = "Mod"
VERIFIED_ROLE_NAME = "Verified"
TICKET_CATEGORY_NAME = "Requests"
REQUIRED_PHOTOS = 3

SETTINGS_FILE = "settings.json"
DEFAULT_SETTINGS = {
    "limit": 5,
    "window": 5,
    "timeout_minutes": 180,
}
