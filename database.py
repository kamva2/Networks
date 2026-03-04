import json
import os
from datetime import datetime

DATABASE_FILE = "client_connections.json"

#Load the client connection database from JSON file, if it does not exist
def load_database():
    
    if os.path.exists(DATABASE_FILE):
        try:
            with open(DATABASE_FILE, 'r') as f:
                data = json.load(f)
                if "users" not in data:
                    data["users"] = []
                if "connections" not in data:
                    data["connections"] = []
                return data
        except:
            return {"users": [], "connections": []}
    return {"users": [], "connections": []}

#Save the client connection database to JSON file
def save_database(data):
    
    with open(DATABASE_FILE, 'w') as f:
        json.dump(data, f, indent=4)


def register_user(alias, password):
    db = load_database()
    alias_str = alias.decode() if isinstance(alias, bytes) else alias
    password_str = password.decode() if isinstance(password, bytes) else password

    for user in db["users"]:
        if user["aliase"] == alias_str:
            return False, "Alias already exists"

    db["users"].append(
        {
            "aliase": alias_str,
            "password": password_str,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
    )
    save_database(db)
    return True, "Registration successful"


def authenticate_user(alias, password):
    db = load_database()
    alias_str = alias.decode() if isinstance(alias, bytes) else alias
    password_str = password.decode() if isinstance(password, bytes) else password

    for user in db["users"]:
        if user["aliase"] == alias_str and user["password"] == password_str:
            return True
    return False


def user_exists(alias):
    db = load_database()
    alias_str = alias.decode() if isinstance(alias, bytes) else alias
    for user in db["users"]:
        if user["aliase"] == alias_str:
            return True
    return False

#Record a client login with timestamp
def record_login(alias, ip_address, port):
    
    db = load_database()
    login_record = {
        "aliase": alias.decode() if isinstance(alias, bytes) else alias,
        "ip_address": ip_address,
        "port": port,
        "login_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "logout_time": None
    }
    db["connections"].append(login_record)
    save_database(db)
    return login_record

#Record a client logout with timestamp
def record_logout(aliase):
    
    db = load_database()
    aliase_str = aliase.decode() if isinstance(aliase, bytes) else aliase
    
    # Find the most recent connection record for this alias without logout time
    for record in reversed(db["connections"]):
        if record["aliase"] == aliase_str and record["logout_time"] is None:
            record["logout_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            save_database(db)
            return record
    return None

#Retrieve all client connections
def get_all_connections():
    
    db = load_database()
    return db["connections"]

#Retrieve only active connections (no logout time)
def get_active_connections():
    
    db = load_database()
    return [conn for conn in db["connections"] if conn["logout_time"] is None]