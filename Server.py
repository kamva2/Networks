import socket
import threading
import database

host = '127.0.0.1'
port = 22081

server = socket.socket(socket.AF_INET,socket.SOCK_STREAM)
server.bind((host,port))
server.listen()
beep_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

#We keeping track of people who have connected to the server with their aliase and the port
clients = []
aliases = []
# We will also keep track of pending private chat requests and active private chat connections
pending_requests = {}
private_partners = {}
groups = {}
group_owners = {}
group_invites = {}
offline_inbox = {}
beep_endpoints = {}

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


def register_beep_endpoint(aliase, ip_address, udp_port):
    beep_endpoints[aliase] = (ip_address, udp_port)


def remove_beep_endpoint(aliase):
    beep_endpoints.pop(aliase, None)


def send_beep(to_alias, from_alias, channel):
    endpoint = beep_endpoints.get(to_alias)
    if endpoint is None:
        return
    try:
        beep_socket.sendto(f"BEEP:{from_alias}:{channel}".encode(), endpoint)
    except:
        pass


# This function resolves alias case-insensitively to the canonical online alias
def resolve_alias(raw_alias):
    for online_alias in aliases:
        if online_alias.lower() == raw_alias.lower():
            return online_alias
    return None

# This function resolves group name case-insensitively to the group name in the server
def resolve_group_name(raw_group_name):
    for group_name in groups:
        if group_name.lower() == raw_group_name.lower():
            return group_name
    return None

# This function resolves a registered alias case-insensitively to the registered username in the database, even if they are not currently online.
# This allows for offline messaging and group invites to work with correct casing when the user is not currently connected.
def resolve_registered_alias(raw_alias):
    db = database.load_database()
    for user in db.get("users", []):
        username = database.get_user_name(user)
        if username and username.lower() == raw_alias.lower():
            return username
    return None


def queue_offline_message(target_alias, message):
    if target_alias not in offline_inbox:
        offline_inbox[target_alias] = []
    offline_inbox[target_alias].append(message)

# This is the function that delivers pending private chat requests, group invites, and offline messages to a client when they connect to the server
def deliver_offline_for_alias(aliase):
    # Redeliver pending private requests that were sent while this user was offline.
    for requester in sorted(pending_requests.get(aliase, set())):
        send_to_alias(aliase, f"PRIVATE_REQUEST_FROM:{requester}")

    # Redeliver pending group invites while preserving inviter information.
    invite_map = group_invites.get(aliase, {})
    for group_name in sorted(invite_map.keys()):
        inviter = invite_map[group_name]
        send_to_alias(aliase, f"GROUP_INVITE:{group_name}:{inviter}")

    # Deliver queued offline messages and clear mailbox.
    queued = offline_inbox.pop(aliase, [])
    for msg in queued:
        send_to_alias(aliase, msg)

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
    # Remove requests sent by this user to others.
    targets_to_remove = []
    for target, requesters in pending_requests.items():
        requesters.discard(aliase)
        if not requesters:
            targets_to_remove.append(target)

    for target in targets_to_remove:
        pending_requests.pop(target, None)


def cleanup_group_invites(aliase):
    group_invites.pop(aliase, None)

# This is the function that cleans up any group memberships, ownerships, and pending invites when a client disconnects or exits the chatroom
def cleanup_groups_for_alias(aliase):
    removed_groups = []
    for group_name, members in list(groups.items()):
        if aliase in members:
            members.discard(aliase)
            if not members:
                removed_groups.append(group_name)
                continue

            for member in members:
                send_to_alias(member, f"INFO: {aliase} left group {group_name}")

            if group_owners.get(group_name) == aliase:
                new_owner = sorted(members)[0]
                group_owners[group_name] = new_owner
                send_to_alias(new_owner, f"INFO: You are now owner of group {group_name}")

    for group_name in removed_groups:
        groups.pop(group_name, None)
        group_owners.pop(group_name, None)

    for invitee, invited_groups in list(group_invites.items()):
        to_remove = [name for name in invited_groups.keys() if name in removed_groups]
        for name in to_remove:
            invited_groups.pop(name, None)
        if not invited_groups:
            group_invites.pop(invitee, None)

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
    cleanup_group_invites(aliase)
    cleanup_groups_for_alias(aliase)
    remove_beep_endpoint(aliase)

    broadcast(f"{aliase} has left the chatroom".encode())
    database.record_logout(aliase)


def handle_create_group(aliase, text):
    group_name = text[len('create group '):].strip()
    if not group_name:
        return "INFO: create group [group_name]"

    existing = resolve_group_name(group_name)
    if existing is not None:
        return f"INFO: Group {existing} already exists"

    groups[group_name] = {aliase}
    group_owners[group_name] = aliase
    return f"GROUP_JOINED:{group_name}"

# This is the function that handles inviting another client to join a group, which can only be done by the group owner
def handle_invite_group(aliase, text):
    payload = text[len('invite group '):].strip()
    parts = payload.split(maxsplit=1)
    if len(parts) < 2:
        return "INFO: invite group [group_name] [client]"

    group_raw, target_raw = parts[0], parts[1].strip()
    group_name = resolve_group_name(group_raw)
    if group_name is None:
        return "INFO: Group does not exist"

    if group_owners.get(group_name) != aliase:
        return "INFO: Only the group owner can invite members"

    target = resolve_alias(target_raw)
    if target is None:
        target = resolve_registered_alias(target_raw)
    if target is None:
        return "INFO: Target alias does not exist"

    if target in groups[group_name]:
        return f"INFO: {target} is already in group {group_name}"

    if target not in group_invites:
        group_invites[target] = {}

    if group_name in group_invites[target].keys():
        return f"INFO: {target} already has an invite to {group_name}"

    group_invites[target][group_name] = aliase
    if target in aliases:
        send_to_alias(target, f"GROUP_INVITE:{group_name}:{aliase}")
        return f"INFO: Group invite sent to {target} for {group_name}"

    return f"INFO: {target} is offline. Group invite queued for delivery."

# This is the function that handles accepting a group invite, which adds the client to the group and notifies all current group members of the new addition
def handle_accept_group(aliase, text):
    group_raw = text[len('accept group '):].strip()
    if not group_raw:
        return "INFO: accept group [group_name]"

    group_name = resolve_group_name(group_raw)
    if group_name is None:
        return "INFO: Group does not exist"

    if aliase not in group_invites or group_name not in group_invites[aliase].keys():
        return f"INFO: No pending invite for group {group_raw}"

    group_invites[aliase].pop(group_name, None)
    if not group_invites[aliase]:
        group_invites.pop(aliase, None)

    groups[group_name].add(aliase)
    for member in groups[group_name]:
        if member != aliase:
            send_to_alias(member, f"INFO: {aliase} joined group {group_name}")
    return f"GROUP_JOINED:{group_name}"

# This is the function that handles rejecting a group invite, which removes the pending invite and notifies the group owner of the rejection
def handle_reject_group(aliase, text):
    group_raw = text[len('reject group '):].strip()
    if not group_raw:
        return "INFO: reject group [group_name]"

    group_name = resolve_group_name(group_raw)
    if group_name is None:
        return "INFO: Group does not exist"

    if aliase not in group_invites or group_name not in group_invites[aliase].keys():
        return f"INFO: No pending invite for group {group_raw}"

    group_invites[aliase].pop(group_name, None)
    if not group_invites[aliase]:
        group_invites.pop(aliase, None)

    owner = group_owners.get(group_name)
    if owner:
        send_to_alias(owner, f"INFO: {aliase} rejected invite to group {group_name}")
    return f"INFO: Rejected invite to group {group_name}"

# This is the function that handles listing all groups that the client is currently a member of
def handle_my_groups(aliase):
    mine = sorted([group_name for group_name, members in groups.items() if aliase in members])
    if not mine:
        return "Groups: none"
    return f"Groups: {', '.join(mine)}"


def handle_group_message(aliase, raw_text):
    payload = raw_text[len('group txt '):].strip()
    parts = payload.split(maxsplit=1)
    if len(parts) < 2:
        return "INFO: group txt [group_name] [message]"

    group_raw, group_text = parts[0], parts[1].strip()
    if not group_text:
        return "INFO: Group message cannot be empty"

    group_name = resolve_group_name(group_raw)
    if group_name is None:
        return "INFO: Group does not exist"

    if aliase not in groups[group_name]:
        return f"INFO: You are not a member of group {group_name}"

    for member in groups[group_name]:
        if member != aliase:
            message = f"[Group:{group_name}] {aliase}: {group_text}"
            if member in aliases:
                send_to_alias(member, message)
                send_beep(member, aliase, f"GROUP:{group_name}")
            else:
                queue_offline_message(member, message)
    return ""
# This is the function that checks if a file transfer can be relayed from the sender to the target client based on their private chat connection status
def can_relay_file(sender_alias, target_alias):
    if target_alias is None:
        return False, "INFO: Target alias is not online"
    if target_alias not in private_partners.get(sender_alias, set()):
        return False, "INFO: No private connection with target"
    return True, ""

# This is the function that handles the initial file transfer request from the sender, which includes the target client, filename, file size, and transfer ID. It checks if the transfer can be relayed and then forwards the file start information to the target client if allowed.
def handle_file_start(sender_alias, raw_text):
    parts = raw_text.split("|", 4)
    if len(parts) != 5:
        return "INFO: Invalid file start packet"

    _, target_raw, filename, size_str, transfer_id = parts
    target_alias = resolve_alias(target_raw)
    allowed, msg = can_relay_file(sender_alias, target_alias)
    if not allowed:
        return msg

    send_to_alias(target_alias, f"FILE_START_FROM|{sender_alias}|{filename}|{size_str}|{transfer_id}")
    return ""

# This is the function that handles relaying file chunks from the sender to the target client during a file transfer
def handle_file_chunk(sender_alias, raw_text):
    parts = raw_text.split("|", 4)
    if len(parts) != 5:
        return ""

    _, target_raw, transfer_id, seq_str, chunk_b64 = parts
    target_alias = resolve_alias(target_raw)
    allowed, _ = can_relay_file(sender_alias, target_alias)
    if not allowed:
        return ""

    send_to_alias(target_alias, f"FILE_CHUNK_FROM|{sender_alias}|{transfer_id}|{seq_str}|{chunk_b64}")
    return ""

# This is the function that handles the end of a file transfer, which notifies the target client that the transfer is complete and includes the total number of chunks received
def handle_file_end(sender_alias, raw_text):
    parts = raw_text.split("|", 3)
    if len(parts) != 4:
        return ""

    _, target_raw, transfer_id, total_chunks = parts
    target_alias = resolve_alias(target_raw)
    allowed, _ = can_relay_file(sender_alias, target_alias)
    if not allowed:
        return ""

    send_to_alias(target_alias, f"FILE_END_FROM|{sender_alias}|{transfer_id}|{total_chunks}")
    return ""

# This is the function that handles the client's request to connect to another client for a private chat
def handle_connect_request(aliase, text):
    requested_alias = text[len('connect to '):].strip()

    if not requested_alias:
        return "INFO: connect to [client]"

    online_target = resolve_alias(requested_alias)
    resolved_target = online_target if online_target is not None else resolve_registered_alias(requested_alias)
    if resolved_target is None:
        return "INFO: Target alias does not exist"

    if resolved_target.lower() == aliase.lower():
        return "INFO: You cannot connect to yourself"

    if resolved_target in private_partners.get(aliase, set()):
        return f"INFO: You already have a private connection with {resolved_target}"

    if resolved_target not in pending_requests:
        pending_requests[resolved_target] = set()

    if aliase in pending_requests[resolved_target]:
        return f"INFO: You already sent a request to {resolved_target}"

    pending_requests[resolved_target].add(aliase)
    if online_target is not None:
        send_to_alias(online_target, f"PRIVATE_REQUEST_FROM:{aliase}")
        return f"INFO: Connection request sent to {online_target}"

    return f"INFO: {resolved_target} is offline. Invitation queued for delivery."

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
    if target is not None:
        if target not in private_partners.get(aliase, set()):
            return f"INFO: No private connection with {target_raw}"
        send_to_alias(target, f"[Private:{target}] {aliase}: {private_text}")
        return ""

    offline_target = resolve_registered_alias(target_raw)
    if offline_target is None:
        return "INFO: Target alias does not exist"

    queue_offline_message(offline_target, f"[Offline Private] {aliase}: {private_text}")
    return f"INFO: {offline_target} is offline. Message queued for delivery."


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
    while True:
        try:
            message = client.recv(1024)
            if not message:
                remove_client(client)
                break

            raw_text = message.decode(errors='ignore').strip()
            text = raw_text.lower()

            if raw_text.startswith("BEEP_UDP_PORT:"):
                try:
                    udp_port = int(raw_text.split(":", 1)[1].strip())
                    if udp_port <= 0 or udp_port > 65535:
                        raise ValueError
                    register_beep_endpoint(aliase, address[0], udp_port)
                    client.send("INFO: UDP beep port registered".encode())
                except:
                    client.send("INFO: Invalid UDP beep port".encode())
                continue

            if raw_text.startswith("FILE_START|"):
                response = handle_file_start(aliase, raw_text)
                if response:
                    client.send(response.encode())
                continue

            if raw_text.startswith("FILE_CHUNK|"):
                handle_file_chunk(aliase, raw_text)
                continue

            if raw_text.startswith("FILE_END|"):
                handle_file_end(aliase, raw_text)
                continue

            if text == 'exit' or text == f'{aliase}: exit'.lower():
                remove_client(client)
                break

            if text == 'online clients':
                online_list = ', '.join(aliases) if aliases else 'No clients online.'
                client.send(f"Online clients: {online_list}".encode())
                continue

            if text.startswith('create group '):
                response = handle_create_group(aliase, raw_text)
                client.send(response.encode())
                continue

            if text.startswith('invite group '):
                response = handle_invite_group(aliase, raw_text)
                client.send(response.encode())
                continue

            if text.startswith('accept group '):
                response = handle_accept_group(aliase, raw_text)
                client.send(response.encode())
                continue

            if text.startswith('reject group '):
                response = handle_reject_group(aliase, raw_text)
                client.send(response.encode())
                continue

            if text == 'my groups':
                response = handle_my_groups(aliase)
                client.send(response.encode())
                continue

            if text.startswith('group txt '):
                response = handle_group_message(aliase, raw_text)
                if response:
                    client.send(response.encode())
                continue

            if text.startswith('connect to '):
                response = handle_connect_request(aliase, raw_text)
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

            # Any free-form message that reaches this point is treated as broadcast text.
            for online_alias in aliases:
                if online_alias != aliase:
                    send_beep(online_alias, aliase, "BROADCAST")
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
        deliver_offline_for_alias(aliase)

        #Then for this program to support multiple clients we have to introduce multi-threading
        thread = threading.Thread(target=handle_client, args=(client, aliase, address))
        thread.start()
receive()
