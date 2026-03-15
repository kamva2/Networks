import socket
import threading
import database

host = '0.0.0.0'
port = 55555

# Create the TCP server socket
server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind((host, port))
server.listen()

# UDP socket used for small beep notifications
beep_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# We keeping track of people who have connected to the server with their aliase
clients = []
aliases = []

# We will also keep track of pending private chat requests and active private chat connections
pending_requests = {}
private_partners = {}

# Group related structures
groups = {}
group_owners = {}
group_invites = {}

# Offline messages for users who are not online
offline_inbox = {}

# Stores the UDP endpoint of each online user for beep notifications
beep_endpoints = {}

# Buffer for each client so we can safely reconstruct newline-delimited packets
client_buffers = {}


# This function sends a text packet and appends a newline so packets are separated properly
def send_packet(sock, text):
    try:
        sock.sendall((text + "\n").encode())
        return True
    except:
        return False


# Have to broadcast a message for the chat box or clients that are connected
def broadcast(message, sender=None):
    for client in clients[:]:
        if client != sender:
            send_packet(client, message)


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
    return send_packet(target_client, message)


# This function registers the UDP beep endpoint for a client
def register_beep_endpoint(aliase, ip_address, udp_port):
    beep_endpoints[aliase] = (ip_address, udp_port)


# This function removes the stored UDP endpoint when a client disconnects
def remove_beep_endpoint(aliase):
    beep_endpoints.pop(aliase, None)


# This function sends a UDP beep notification to a specific client
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
def resolve_registered_alias(raw_alias):
    db = database.load_database()
    for user in db.get("users", []):
        username = database.get_user_name(user)
        if username and username.lower() == raw_alias.lower():
            return username
    return None


# This function stores a message in the offline inbox for a user
def queue_offline_message(target_alias, message):
    if target_alias not in offline_inbox:
        offline_inbox[target_alias] = []
    offline_inbox[target_alias].append(message)


# This is the function that delivers pending private chat requests, group invites, and offline messages to a client when they connect to the server
def deliver_offline_for_alias(aliase):
    # Redeliver pending private requests that were sent while this user was offline
    for requester in sorted(pending_requests.get(aliase, set())):
        send_to_alias(aliase, f"PRIVATE_REQUEST_FROM:{requester}")

    # Redeliver pending group invites while preserving inviter information
    invite_map = group_invites.get(aliase, {})
    for group_name in sorted(invite_map.keys()):
        inviter = invite_map[group_name]
        send_to_alias(aliase, f"GROUP_INVITE:{group_name}:{inviter}")

    # Deliver queued offline messages and clear mailbox
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

    # Notify only if online
    if aliase_a in aliases:
        send_to_alias(aliase_a, f"PRIVATE_ENDED:{aliase_b}:{reason}")
    if aliase_b in aliases:
        send_to_alias(aliase_b, f"PRIVATE_ENDED:{aliase_a}:{reason}")


# This is the function that cleans up any pending private chat requests when a client disconnects or exits the chatroom
def cleanup_pending_requests(aliase):
    targets_to_remove = []
    for target, requesters in pending_requests.items():
        requesters.discard(aliase)
        if not requesters:
            targets_to_remove.append(target)

    for target in targets_to_remove:
        pending_requests.pop(target, None)


# This function removes any outstanding group invites for a user
def cleanup_group_invites(aliase):
    # Do NOT remove invites TO this user, because they may be offline and still need them later.
    # Only remove invites sent BY this user as inviter.
    for invitee, invite_map in list(group_invites.items()):
        groups_to_remove = [g for g, inviter in invite_map.items() if inviter == aliase]
        for g in groups_to_remove:
            invite_map.pop(g, None)
        if not invite_map:
            group_invites.pop(invitee, None)


# This function cleans up group ownership if the owner disconnects, but DOES NOT remove the user from groups. Group membership persists offline.
def cleanup_groups_for_alias(aliase):
    for group_name, members in list(groups.items()):
        if aliase in members and group_owners.get(group_name) == aliase:
            online_members = sorted([m for m in members if m in aliases and m != aliase])
            if online_members:
                new_owner = online_members[0]
                group_owners[group_name] = new_owner
                send_to_alias(new_owner, f"INFO: You are now owner of group {group_name}")


# This is the function that removes the client from the server when they disconnect or exit the chatroom
def remove_client(client):
    if client not in clients:
        client_buffers.pop(client, None)
        try:
            client.close()
        except:
            pass
        return

    index = clients.index(client)
    clients.remove(client)
    aliase = aliases[index]
    aliases.remove(aliase)
    client_buffers.pop(client, None)

    try:
        client.close()
    except:
        pass

    cleanup_pending_requests(aliase)

    # We do NOT end private connections here anymore.
    # Private chats should persist even when a user disconnects.

    cleanup_group_invites(aliase)

    # We do NOT remove the user from groups here anymore.
    # Group membership should persist even when offline.
    cleanup_groups_for_alias(aliase)

    remove_beep_endpoint(aliase)

    broadcast(f"{aliase} has left the chatroom")
    database.record_logout(aliase)


# This function handles creating a new group
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

    if group_name in group_invites[target]:
        return f"INFO: {target} already has an invite to {group_name}"

    group_invites[target][group_name] = aliase
    if target in aliases:
        send_to_alias(target, f"GROUP_INVITE:{group_name}:{aliase}")
        return f"INFO: Group invite sent to {target} for {group_name}"

    return f"INFO: {target} is offline. Group invite queued for delivery."


# This is the function that handles accepting a group invite, which adds the client to the group and notifies all current group members
def handle_accept_group(aliase, text):
    group_raw = text[len('accept group '):].strip()
    if not group_raw:
        return "INFO: accept group [group_name]"

    group_name = resolve_group_name(group_raw)
    if group_name is None:
        return "INFO: Group does not exist"

    if aliase not in group_invites or group_name not in group_invites[aliase]:
        return f"INFO: No pending invite for group {group_raw}"

    group_invites[aliase].pop(group_name, None)
    if not group_invites[aliase]:
        group_invites.pop(aliase, None)

    groups[group_name].add(aliase)
    for member in groups[group_name]:
        if member != aliase and member in aliases:
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

    if aliase not in group_invites or group_name not in group_invites[aliase]:
        return f"INFO: No pending invite for group {group_raw}"

    inviter = group_invites[aliase].pop(group_name, None)
    if not group_invites[aliase]:
        group_invites.pop(aliase, None)

    if inviter and inviter in aliases:
        send_to_alias(inviter, f"INFO: {aliase} rejected invite to group {group_name}")
    return f"INFO: Rejected invite to group {group_name}"


# This is the function that handles listing all groups that the client is currently a member of
def handle_my_groups(aliase):
    mine = sorted([group_name for group_name, members in groups.items() if aliase in members])
    if not mine:
        return "Groups: none"
    return f"Groups: {', '.join(mine)}"


# This function handles sending a group message to all group members except the sender
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


# This is the function that handles the initial file transfer request from the sender, which includes the target client, filename, file size, and transfer ID
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
    send_beep(target_alias, sender_alias, "FILE")
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


# This is the function that handles the end of a file transfer, which notifies the target client that the transfer is complete
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
        target = resolve_registered_alias(target_raw)

    if target is None:
        return "INFO: Target alias does not exist"

    if target not in private_partners.get(aliase, set()):
        return f"INFO: You do not have a private connection with {target_raw}"

    remove_private_connection(aliase, target, "ended by command")
    return f"INFO: Private connection with {target} ended"


# This is the function that sends one private message to a selected connected partner and also supports offline delivery if that partner is offline
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

    target_online = resolve_alias(target_raw)
    target_registered = resolve_registered_alias(target_raw)

    if target_online is None and target_registered is None:
        return "INFO: Target alias does not exist"

    target = target_online if target_online is not None else target_registered

    if target not in private_partners.get(aliase, set()):
        return f"INFO: No private connection with {target_raw}"

    if target_online is not None:
        send_to_alias(target_online, f"[Private:{aliase}] {aliase}: {private_text}")
        send_beep(target_online, aliase, "PRIVATE")
        return ""

    queue_offline_message(target, f"[Offline Private] {aliase}: {private_text}")
    return f"INFO: {target} is offline. Message queued for delivery."


# This function reads one complete line from a client using the per-client buffer
def recv_line(client):
    while True:
        try:
            if client not in client_buffers:
                client_buffers[client] = b""

            if b"\n" in client_buffers[client]:
                line, rest = client_buffers[client].split(b"\n", 1)
                client_buffers[client] = rest
                return line.decode(errors="ignore").rstrip("\r")

            chunk = client.recv(4096)
            if not chunk:
                client_buffers.pop(client, None)
                return None

            client_buffers[client] += chunk

        except (ConnectionResetError, ConnectionAbortedError, OSError):
            client_buffers.pop(client, None)
            return None


# This is the function that authenticates the client when they first connect to the server
def authenticate_client(client):
    try:
        while True:
            if not send_packet(client, "Authorise MODE? (REGISTER/LOGIN)"):
                return None

            mode = recv_line(client)
            if mode is None:
                return None
            mode = mode.strip().upper()

            if mode not in ("REGISTER", "LOGIN"):
                send_packet(client, "ERROR: Invalid authentication mode")
                continue

            if not send_packet(client, "ALIAS?"):
                return None

            aliase = recv_line(client)
            if aliase is None:
                return None
            aliase = aliase.strip()

            if not send_packet(client, "PASSWORD?"):
                return None

            password = recv_line(client)
            if password is None:
                return None
            password = password.strip()

            if not aliase or not password:
                send_packet(client, "ERROR: Alias and password are required")
                continue

            if mode == "REGISTER":
                success, msg = database.register_user(aliase, password)
                if not success:
                    send_packet(client, f"ERROR: {msg}")
                    continue
                send_packet(client, "Registration successful. You can login now.")
                continue

            if not database.authenticate_user(aliase, password):
                send_packet(client, "ERROR: Invalid alias or password")
                continue

            if aliase in aliases:
                send_packet(client, "This alias is already logged in")
                continue

            send_packet(client, "AUTH_SUCCESS")
            return aliase

    except (ConnectionResetError, ConnectionAbortedError, OSError):
        client_buffers.pop(client, None)
        return None


# Handling the movements of clients in the chatbox
def handle_client(client, aliase, address):
    while True:
        try:
            raw_text = recv_line(client)
            if raw_text is None:
                remove_client(client)
                break

            raw_text = raw_text.strip()
            text = raw_text.lower()

            if raw_text.startswith("BEEP_UDP_PORT:"):
                try:
                    udp_port = int(raw_text.split(":", 1)[1].strip())
                    if udp_port <= 0 or udp_port > 65535:
                        raise ValueError
                    register_beep_endpoint(aliase, address[0], udp_port)
                    send_packet(client, "INFO: UDP beep port registered")
                except:
                    send_packet(client, "INFO: Invalid UDP beep port")
                continue

            if raw_text.startswith("FILE_START|"):
                response = handle_file_start(aliase, raw_text)
                if response:
                    send_packet(client, response)
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
                send_packet(client, f"Online clients: {online_list}")
                continue

            if text.startswith('create group '):
                send_packet(client, handle_create_group(aliase, raw_text))
                continue

            if text.startswith('invite group '):
                send_packet(client, handle_invite_group(aliase, raw_text))
                continue

            if text.startswith('accept group '):
                send_packet(client, handle_accept_group(aliase, raw_text))
                continue

            if text.startswith('reject group '):
                send_packet(client, handle_reject_group(aliase, raw_text))
                continue

            if text == 'my groups':
                send_packet(client, handle_my_groups(aliase))
                continue

            if text.startswith('group txt '):
                response = handle_group_message(aliase, raw_text)
                if response:
                    send_packet(client, response)
                continue

            if text.startswith('connect to '):
                send_packet(client, handle_connect_request(aliase, raw_text))
                continue

            if text.startswith('accept connection '):
                send_packet(client, handle_accept_request(aliase, raw_text))
                continue

            if text.startswith('reject connection '):
                send_packet(client, handle_reject_request(aliase, raw_text))
                continue

            if text.startswith('end private '):
                send_packet(client, handle_end_private_request(aliase, raw_text))
                continue

            if text == 'my private chats':
                partners = sorted(private_partners.get(aliase, set()))
                if partners:
                    send_packet(client, f"Private chats: {', '.join(partners)}")
                else:
                    send_packet(client, "Private chats: none")
                continue

            if text.startswith('private txt '):
                response = handle_private_message(aliase, raw_text)
                if response:
                    send_packet(client, response)
                continue

            # Any free-form message that reaches this point is treated as broadcast text
            for online_alias in aliases:
                if online_alias != aliase:
                    send_beep(online_alias, aliase, "BROADCAST")
            broadcast(raw_text, sender=client)

        except:
            remove_client(client)
            break


# This is the main function that receives the client's connection
def receive():
    while True:
        print("Server is running and listening...")
        try:
            client, address = server.accept()
            print(f"connection is established with {str(address)}")

            aliase = authenticate_client(client)
            if aliase is None:
                client_buffers.pop(client, None)
                try:
                    client.close()
                except:
                    pass
                continue

            aliases.append(aliase)
            clients.append(client)
            client_buffers[client] = b""

            print(f"The aliase of this client is {aliase}")

            # Recording login to JSON database
            ip_address = address[0]
            port_num = address[1]
            database.record_login(aliase, ip_address, port_num)

            broadcast(f"{aliase} has connected to the chatroom")
            send_packet(client, "you are now connected")
            deliver_offline_for_alias(aliase)

            # Then for this program to support multiple clients we have to introduce multi-threading
            thread = threading.Thread(target=handle_client, args=(client, aliase, address), daemon=True)
            thread.start()

        except Exception as e:
            print(f"Server accept/auth error: {e}")


receive()