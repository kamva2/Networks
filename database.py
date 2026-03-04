import json
import os
from datetime import datetime

DATABASE_FILE = "client_connections.json"

#Load the client connection database from JSON file, if it does not exist
def load_database():
    
    if os.path.exists(DATABASE_FILE):
        try:
            with open(DATABASE_FILE, 'r') as f:
                return json.load(f)
        except:
            return {"connections": []}
    return {"connections": []}

#Save the client connection database to JSON file
def save_database(data):
    
    with open(DATABASE_FILE, 'w') as f:
        json.dump(data, f, indent=4)

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