import socket
import threading
import database

host = '127.0.0.1'
port = 12345

server = socket.socket(socket.AF_INET,socket.SOCK_STREAM)
server.bind((host,port))
server.listen()

#We keeping track of people who have connected to the server with their aliase and the port
clients = []
aliases = []
# We will also keep track of pending private chat requests and active private chat connections
pending_requests = {}
private_partners = {}
client_udp_ports = {}
client_ips = {}

#Have to broadcast a message for the chat box or clients that are connected
def broadcast(message, sender=None):
    for client in clients:
        if client != sender:
            client.send(message)

# This is the function that retrieves the client socket object based on their aliase
def get_client_by_alias(aliase):
    if aliase not in aliases:
        return None
    index = aliases.index(aliase)
    return clients[index]

# This is the function that sends a message to a specific client based on their aliase
def send_to_alias(aliase, message):
    target_client = get_client_by_alias(aliase)
    if target_client is None:
        return False
    try:
        target_client.send(message.encode())
        return True
    except:
        return False

# This function resolves alias case-insensitively to the canonical online alias
def resolve_alias(raw_alias):
    for online_alias in aliases:
        if online_alias.lower() == raw_alias.lower():
            return online_alias
    return None

# This function ensures an alias has a private partner set initialized
def ensure_private_partner_set(aliase):
    if aliase not in private_partners:
        private_partners[aliase] = set()

# This function creates a two-way private connection between users
def add_private_connection(aliase_a, aliase_b):
    ensure_private_partner_set(aliase_a)
    ensure_private_partner_set(aliase_b)
    private_partners[aliase_a].add(aliase_b)
    private_partners[aliase_b].add(aliase_a)

# This function removes a two-way private connection and notifies both users
def remove_private_connection(aliase_a, aliase_b, reason):
    if aliase_a in private_partners:
        private_partners[aliase_a].discard(aliase_b)
        if not private_partners[aliase_a]:
            private_partners.pop(aliase_a, None)

    if aliase_b in private_partners:
        private_partners[aliase_b].discard(aliase_a)
        if not private_partners[aliase_b]:
            private_partners.pop(aliase_b, None)

    send_to_alias(aliase_a, f"PRIVATE_ENDED:{aliase_b}:{reason}")
    send_to_alias(aliase_b, f"PRIVATE_ENDED:{aliase_a}:{reason}")

# This is the function that ends a private chat connection between two clients
def end_private_connection(aliase):
    partners = list(private_partners.get(aliase, set()))
    for partner in partners:
        remove_private_connection(aliase, partner, "disconnected")

# This is the function that cleans up any pending private chat requests when a client disconnects or exits the chatroom
def cleanup_pending_requests(aliase):
    # Notify everyone who requested this user.
    if aliase in pending_requests:
        requesters = list(pending_requests.pop(aliase))
        for requester in requesters:
            send_to_alias(requester, f"INFO: {aliase} is no longer available for private chat")

    # Remove requests sent by this user to others.
    targets_to_remove = []
    for target, requesters in pending_requests.items():
        requesters.discard(aliase)
        if not requesters:
            targets_to_remove.append(target)

    for target in targets_to_remove:
        pending_requests.pop(target, None)

# This is the function that cleans up any UDP state when a client disconnects or exits the chatroom
def cleanup_udp_state(aliase):
    client_udp_ports.pop(aliase, None)
    client_ips.pop(aliase, None)

# This is the function that removes the client from the server when they disconnect or exit the chatroom
def remove_client(client):
    if client not in clients:
        return

    index = clients.index(client)
    clients.remove(client)
    aliase = aliases[index]
    aliases.remove(aliase)

    try:
        client.close()
    except:
        pass

    cleanup_pending_requests(aliase)
    end_private_connection(aliase)
    cleanup_udp_state(aliase)

    broadcast(f"{aliase} has left the chatroom".encode())
    database.record_logout(aliase)

# This is the function that handles the client's request to connect to another client for a private UDP file transfer
def handle_udp_connect_request(aliase, text):
    target_raw = text[len('udp connect '):].strip()
    if not target_raw:
        return "INFO: udp connect [client]"

    target = resolve_alias(target_raw)
    if target is None:
        return "INFO: Target alias is not online"

    if target not in private_partners.get(aliase, set()):
        return f"INFO: No private connection with {target_raw}"

    sender_port = client_udp_ports.get(aliase)
    target_port = client_udp_ports.get(target)
    sender_ip = client_ips.get(aliase)
    target_ip = client_ips.get(target)

    if not sender_port:
        return "INFO: Your UDP endpoint is not registered"

    if not target_port or not target_ip:
        return f"INFO: {target} UDP endpoint is not registered"

    # Share peer endpoint with both clients so either side can send files.
    send_to_alias(aliase, f"UDP_PEER:{target}:{target_ip}:{target_port}")
    send_to_alias(target, f"UDP_PEER:{aliase}:{sender_ip}:{sender_port}")
    return f"INFO: UDP peer linked with {target}"

# This is the function that handles the client's request to connect to another client for a private chat
def handle_connect_request(aliase, text):
    requested_alias = text[len('connect to '):].strip()

    if not requested_alias:
        return "INFO: connect to [client]"

    requested_alias = resolve_alias(requested_alias)
    if requested_alias is None:
        return "INFO: Target alias is not online"

    if requested_alias == aliase:
        return "INFO: You cannot connect to yourself"

    if requested_alias in private_partners.get(aliase, set()):
        return f"INFO: You already have a private connection with {requested_alias}"

    if requested_alias not in pending_requests:
        pending_requests[requested_alias] = set()

    if aliase in pending_requests[requested_alias]:
        return f"INFO: You already sent a request to {requested_alias}"

    pending_requests[requested_alias].add(aliase)
    send_to_alias(requested_alias, f"PRIVATE_REQUEST_FROM:{aliase}")
    return f"INFO: Connection request sent to {requested_alias}"

# This is the function that handles the client's request to accept a private chat request
def handle_accept_request(aliase, text):
    requester_raw = text[len('accept connection '):].strip()
    if not requester_raw:
        return "INFO: accept connection [client]"

    requester = resolve_alias(requester_raw)
    if requester is None:
        return "INFO: Requester is no longer online"

    if aliase not in pending_requests or requester not in pending_requests[aliase]:
        return f"INFO: No pending request from {requester_raw}"

    pending_requests[aliase].discard(requester)
    if not pending_requests[aliase]:
        pending_requests.pop(aliase, None)

    add_private_connection(aliase, requester)
    send_to_alias(requester, f"PRIVATE_CONNECTED:{aliase}")
    return f"PRIVATE_CONNECTED:{requester}"

# This is the function that handles the client's request to reject a private chat request
def handle_reject_request(aliase, text):
    requester_raw = text[len('reject connection '):].strip()
    if not requester_raw:
        return "INFO: reject connection [client]"

    requester = resolve_alias(requester_raw)
    if requester is None:
        return "INFO: Requester is no longer online"

    if aliase not in pending_requests or requester not in pending_requests[aliase]:
        return f"INFO: No pending request from {requester_raw}"

    pending_requests[aliase].discard(requester)
    if not pending_requests[aliase]:
        pending_requests.pop(aliase, None)

    send_to_alias(requester, f"PRIVATE_REJECTED:{aliase}")
    return f"INFO: Rejected private request from {requester}"

# This is the function that handles ending one private connection by alias
def handle_end_private_request(aliase, text):
    target_raw = text[len('end private '):].strip()
    if not target_raw:
        return "INFO: end private [client]"

    target = resolve_alias(target_raw)
    if target is None:
        return "INFO: Target alias is not online"

    if target not in private_partners.get(aliase, set()):
        return f"INFO: You do not have a private connection with {target_raw}"

    remove_private_connection(aliase, target, "ended by command")
    return f"INFO: Private connection with {target} ended"

# This is the function that sends one private message to a selected connected partner
def handle_private_message(aliase, raw_text):
    payload = raw_text[12:].strip()
    if not payload:
        return "INFO: private txt [client] [message]"

    parts = payload.split(maxsplit=1)
    if len(parts) < 2:
        return "INFO: private txt [client] [message]"

    target_raw, private_text = parts[0], parts[1].strip()
    if not private_text:
        return "INFO: Private message cannot be empty"

    target = resolve_alias(target_raw)
    if target is None:
        return "INFO: Target alias is not online"

    if target not in private_partners.get(aliase, set()):
        return f"INFO: No private connection with {target_raw}"

    send_to_alias(target, f"[Private:{target}] {aliase}: {private_text}")
    return ""


# This is the function that authenticates the client when they first connect to the server
def authenticate_client(client):
    while True:
        client.send("Authorise MODE? (REGISTER/LOGIN)".encode())
        mode = client.recv(1024).decode().strip().upper()

        if mode not in ("REGISTER", "LOGIN"):
            client.send("ERROR: Invalid authentication mode".encode())
            continue

        client.send("ALIAS?".encode())
        aliase = client.recv(1024).decode().strip()

        client.send("PASSWORD?".encode())
        password = client.recv(1024).decode().strip()

        if not aliase or not password:
            client.send("ERROR: Alias and password are required".encode())
            continue

        if mode == "REGISTER":
            success, msg = database.register_user(aliase, password)
            if not success:
                client.send(f"ERROR: {msg}".encode())
                continue
            client.send("Registration successful. You can login now.".encode())
            continue

        if not database.authenticate_user(aliase, password):
            client.send("ERROR: Invalid alias or password".encode())
            continue

        if aliase in aliases:
            client.send("This alias is already logged in".encode())
            continue

        client.send("AUTH_SUCCESS".encode())
        return aliase

# Handling the movements of clients in the chatbox
def handle_client(client, aliase, address):

    client_ips[aliase] = address[0]

    while True:
        try:
            message = client.recv(1024)
            if not message:
                remove_client(client)
                break

            raw_text = message.decode(errors='ignore').strip()
            text = raw_text.lower()
            if text == 'exit' or text == f'{aliase}: exit'.lower():
                remove_client(client)
                break

            if text == 'online clients':
                online_list = ', '.join(aliases) if aliases else 'No clients online.'
                client.send(f"Online clients: {online_list}".encode())
                continue

            if text.startswith('connect to '):
                response = handle_connect_request(aliase, raw_text)
                client.send(response.encode())
                continue

            if raw_text.startswith('UDP_PORT:'):
                try:
                    udp_port = int(raw_text.split(':', 1)[1].strip())
                    if udp_port <= 0 or udp_port > 65535:
                        raise ValueError
                    client_udp_ports[aliase] = udp_port
                    client.send(f"INFO: UDP port {udp_port} registered".encode())
                except:
                    client.send("INFO: Invalid UDP port registration".encode())
                continue

            if text.startswith('udp connect '):
                response = handle_udp_connect_request(aliase, raw_text)
                client.send(response.encode())
                continue

            if text.startswith('accept connection '):
                response = handle_accept_request(aliase, raw_text)
                client.send(response.encode())
                continue

            if text.startswith('reject connection '):
                response = handle_reject_request(aliase, raw_text)
                client.send(response.encode())
                continue

            if text.startswith('end private '):
                response = handle_end_private_request(aliase, raw_text)
                client.send(response.encode())
                continue

            if text == 'my private chats':
                partners = sorted(private_partners.get(aliase, set()))
                if partners:
                    client.send(f"Private chats: {', '.join(partners)}".encode())
                else:
                    client.send("Private chats: none".encode())
                continue

            if text.startswith('private txt '):
                response = handle_private_message(aliase, raw_text)
                if response:
                    client.send(response.encode())
                continue

            broadcast(message, sender=client)
        except:
            remove_client(client)
            break

# This is the main function that recieves the client's connection
def receive():
    while True:
        print("Server is running and listening...")
        client,address = server.accept()
            
        print(f"connection is established with {str(address)}")
        aliase = authenticate_client(client)
        aliases.append(aliase)
        clients.append(client)
        print(f"The aliase of this client is {aliase}")

        # Recording login to JSON database
        ip_address = address[0]
        port_num = address[1]
        database.record_login(aliase, ip_address, port_num)
        
        
        broadcast(f"{aliase} has connected to the chatroom".encode())
        client.send("you are now connected".encode())

        #Then for this program to support multiple clients we have to introduce multi-threading
        thread = threading.Thread(target=handle_client, args=(client, aliase, address))
        thread.start()
receive()
