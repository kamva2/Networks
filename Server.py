import socket
import threading
import json
import database

HOST = "0.0.0.0"
PORT = 12345
PROTOCOL_VERSION = "KV/2.0"

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.bind((HOST, PORT))
server.listen()

state_lock = threading.Lock()

#Keep track of online users and pending peer connection requests
online_clients = {}  # username -> {"socket": sock, "ip": ip, "tcp": int, "udp": int}
pending_requests = set()  # (from_user, to_user)


def read_request(sock_file):
    # Read the start line, I got help from GenAI for this part: it is safety request framing
    start = sock_file.readline()
    if not start:
        return None
    start = start.strip()
    if not start:
        return None

    parts = start.split(" ", 2)
    if len(parts) != 3:
        return {"error": "Bad start line"}

    method, path, version = parts
    headers = {}

    while True:
        line = sock_file.readline()
        if not line:
            break
        line = line.rstrip("\n")
        if line == "":
            break
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip()] = value.strip()

    content_length = int(headers.get("Content-Length", "0"))
    body = sock_file.read(content_length) if content_length > 0 else ""

    return {
        "method": method.upper(),
        "path": path,
        "version": version,
        "headers": headers,
        "body": body
    }


def send_response(sock, code, reason, headers=None, body=""):
    if headers is None:
        headers = {}
    body = body 
    headers = dict(headers)
    headers["Content-Length"] = str(len(body.encode()))

    lines = [f"{PROTOCOL_VERSION} {code} {reason}"]
    for k, v in headers.items():
        lines.append(f"{k}: {v}")
    lines.append("")
    packet = "\n".join(lines) + body
    sock.sendall(packet.encode())


def send_event(sock, event_path, headers=None, body=""):
    if headers is None:
        headers = {}
    body = body
    headers = dict(headers)
    headers["Content-Length"] = str(len(body.encode()))

    lines = [f"EVENT {event_path} {PROTOCOL_VERSION}"]
    for k, v in headers.items():
        lines.append(f"{k}: {v}")
    lines.append("")
    packet = "\n".join(lines) + body
    sock.sendall(packet.encode())


def get_client(username):
    with state_lock:
        return online_clients.get(username)


def handle_client(client_socket, address):
    username = None
    sock_file = client_socket.makefile("r", encoding="utf-8", newline="\n")

    try:
        while True:
            req = read_request(sock_file)
            if req is None:
                break
            if "error" in req:
                send_response(client_socket, 400, "Bad Request")
                continue

            method = req["method"]
            path = req["path"]
            h = req["headers"]
            body = req["body"]

            # REGISTER /auth kv/2.0
            if method == "REGISTER" and path == "/auth":
                user = h.get("Username", "")
                password = h.get("Password", "")
                ok = database.register_user(user, password)
                if ok:
                    send_response(client_socket, 201, "Created")
                else:
                    send_response(client_socket, 409, "Conflict", body="Username already exists")
                continue

            # LOGIN /auth kv/2.0
            if method == "LOGIN" and path == "/auth":
                user = h.get("Username", "")
                password = h.get("Password", "")
                p2p_tcp = int(h.get("P2P-TCP-Port", "0"))
                p2p_udp = int(h.get("P2P-UDP-Port", "0"))

                if not database.authenticate_user(user, password):
                    send_response(client_socket, 401, "Unauthorized")
                    continue

                with state_lock:
                    online_clients[user] = {
                        "socket": client_socket,
                        "ip": address[0],
                        "tcp": p2p_tcp,
                        "udp": p2p_udp
                    }
                database.set_online(user, address[0], p2p_tcp, p2p_udp)
                username = user
                send_response(client_socket, 200, "OK")
                continue

            # Require login after this point
            if not username:
                send_response(client_socket, 403, "Forbidden", body="Login required")
                continue

            # LIST /users kv/2.0
            if method == "LIST" and path == "/users":
                users = database.get_online_users()  # TODO: return list of dicts
                send_response(
                    client_socket, 200, "OK",
                    headers={"Content-Type": "application/json"},
                    body=json.dumps(users)
                )
                continue

            # CONNECT /peer kv/2.0   Header: Target-User
            if method == "CONNECT" and path == "/peer":
                target = h.get("Target-User", "")
                target_info = get_client(target)
                if not target_info:
                    send_response(client_socket, 404, "Not Found", body="Target offline")
                    continue

                with state_lock:
                    pending_requests.add((username, target))

                send_event(
                    target_info["socket"], "/peer/request",
                    headers={"From-User": username}
                )
                send_response(client_socket, 202, "Accepted")
                continue

            # ACCEPT /peer kv/2.0   Header: Target-User
            if method == "ACCEPT" and path == "/peer":
                requester = h.get("Target-User", "")
                with state_lock:
                    if (requester, username) not in pending_requests:
                        send_response(client_socket, 404, "Not Found", body="No pending request")
                        continue
                    pending_requests.remove((requester, username))
                    req_info = online_clients.get(requester)
                    me_info = online_clients.get(username)

                if not req_info or not me_info:
                    send_response(client_socket, 410, "Gone")
                    continue

                # Send each peer the other's endpoint
                send_event(
                    req_info["socket"], "/peer/ready",
                    headers={
                        "Peer-User": username,
                        "Peer-IP": me_info["ip"],
                        "Peer-TCP-Port": str(me_info["tcp"]),
                        "Peer-UDP-Port": str(me_info["udp"])
                    }
                )
                send_event(
                    me_info["socket"], "/peer/ready",
                    headers={
                        "Peer-User": requester,
                        "Peer-IP": req_info["ip"],
                        "Peer-TCP-Port": str(req_info["tcp"]),
                        "Peer-UDP-Port": str(req_info["udp"])
                    }
                )
                send_response(client_socket, 200, "OK")
                continue

            # REJECT /peer kv/2.0
            if method == "REJECT" and path == "/peer":
                requester = h.get("Target-User", "")
                with state_lock:
                    pending_requests.discard((requester, username))
                req_info = get_client(requester)
                if req_info:
                    send_event(req_info["socket"], "/peer/rejected", headers={"By-User": username})
                send_response(client_socket, 200, "OK")
                continue

            # QUIT /session kv/2.0
            if method == "QUIT" and path == "/session":
                send_response(client_socket, 200, "Bye")
                break

            send_response(client_socket, 404, "Not Found")

    finally:
        if username:
            with state_lock:
                online_clients.pop(username, None)
                pending_requests_copy = list(pending_requests)
                for pair in pending_requests_copy:
                    if username in pair:
                        pending_requests.discard(pair)
            database.set_offline(username)

        try:
            client_socket.close()
        except OSError:
            pass


def receive():
    print(f"Server running on {HOST}:{PORT}")
    while True:
        client_socket, address = server.accept()
        thread = threading.Thread(target=handle_client, args=(client_socket, address), daemon=True)
        thread.start()


receive()