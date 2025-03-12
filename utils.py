#stuff that pretty much everything needs
from globals import TOKEN, GUILD_ID, TARGET_MEMBER_ID, TARGET_USER_ID, DATA_FILE, ALLOWED_ROLES, STOCK_FILE, STOCK_HISTORY_FILE, UPDATE_INTERVAL_MINUTES, LOTTERY_FILE, AFK_CHANNEL_ID
import os
import json

def load_data():
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)