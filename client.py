import threading
import socket
import os
import base64
import uuid

server_ip = input("Enter server IP address: ")
client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
client.connect((server_ip, 22081))
beep_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
beep_socket.bind(("", 0))
beep_port = beep_socket.getsockname()[1]
aliase = ""
private_partners = set()
pending_requesters = set()
groups = set()
pending_group_invites = set()
incoming_transfers = {}


def register_beep_port():
    try:
        client.send(f"BEEP_UDP_PORT:{beep_port}".encode())
    except:
        print("Failed to register UDP beep port")


def beep_receive():
    while True:
        try:
            payload, _ = beep_socket.recvfrom(4096)
            text = payload.decode(errors='ignore')
            if not text.startswith("BEEP:"):
                continue

            parts = text.split(":", 2)
            if len(parts) != 3:
                continue

            sender = parts[1].strip()
            channel = parts[2].strip()
            print(f"\a[Beep] {sender} sent a message in {channel}")
        except:
            break

# Keep only basename to prevent writing outside project folders.
def safe_filename(name):
    
    return os.path.basename(name)

#Load the client connection database from JSON file, or create a new one if it doesn't exist
def ensure_download_dir():
    download_dir = os.path.join(os.getcwd(), "downloads")
    os.makedirs(download_dir, exist_ok=True)
    return download_dir

def finalize_incoming_transfer(sender, transfer_id, total_chunks):
    transfer = incoming_transfers.get(transfer_id)
    if transfer is None:
        return

    chunks = transfer["chunks"]
    missing = [idx for idx in range(total_chunks) if idx not in chunks]
    if missing:
        print(f"File from {sender} incomplete. Missing {len(missing)} chunks")
        incoming_transfers.pop(transfer_id, None)
        return

    file_bytes = b"".join(chunks[idx] for idx in range(total_chunks))
    download_dir = ensure_download_dir()
    out_path = os.path.join(download_dir, transfer["filename"])
    with open(out_path, "wb") as out_file:
        out_file.write(file_bytes)

    print(f"File received from {sender}: {out_path}")
    incoming_transfers.pop(transfer_id, None)


# This sends file chunks to server over TCP, and server relays them to the private target.
def send_file_via_tcp(target, file_path):
    if not os.path.isfile(file_path):
        print(f"File not found: {file_path}")
        return

    try:
        with open(file_path, "rb") as file_obj:
            data = file_obj.read()
    except Exception as ex:
        print(f"Failed to read file: {ex}")
        return

    filename = os.path.basename(file_path)
    transfer_id = str(uuid.uuid4())
    chunk_size = 400
    total_chunks = (len(data) + chunk_size - 1) // chunk_size

    try:
        client.send(f"FILE_START|{target}|{filename}|{len(data)}|{transfer_id}".encode())
        for idx in range(total_chunks):
            chunk = data[idx * chunk_size:(idx + 1) * chunk_size]
            chunk_b64 = base64.b64encode(chunk).decode()
            client.send(f"FILE_CHUNK|{target}|{transfer_id}|{idx}|{chunk_b64}".encode())
        client.send(f"FILE_END|{target}|{transfer_id}|{total_chunks}".encode())
        print(f"File sent to {target}: {filename}")
    except Exception as ex:
        print(f"Failed to send file over TCP: {ex}")

# This is the function that handles the authentication process with the server, including registering or logging in, and setting the aliase for the client
def authenticate():
    global aliase

    while True:
        try:
            message = client.recv(1024).decode()
        except:
            print("An error occurred during authentication!")
            client.close()
            return False

        if message.startswith("Authorise MODE?"):
            mode = input("Choose auth mode (REGISTER/LOGIN): ").strip().upper()
            client.send(mode.encode())
        elif message == "ALIAS?":
            aliase = input("Enter aliase name: ").strip()
            client.send(aliase.encode())
        elif message == "PASSWORD?":
            password = input("Enter password: ").strip()
            client.send(password.encode())
        elif message.startswith("ERROR:") or message.startswith("INFO:"):
            print(message)
        elif message in ("AUTH_SUCCESS", "SUCCESSFULLY AUTHENTICATE"):
            print("Authentication successful, Welcome to Chat77!")
            print(
                "User Commands:\n"
                "To broadcast text - bdct txt {your message}\n"
                "To check for online users - online clients\n"
                "To connect with a user - connect to [client]\n"
                "To accept connection - accept connection [client]\n"
                "To reject connection - reject connection [client]\n"
                "To list private chats - my private chats\n"
                "To send private text - private txt [client] {your message}\n"
                "To create group - create group [group_name]\n"
                "To invite to group - invite group [group_name] [client]\n"
                "To accept group invite - accept group [group_name]\n"
                "To reject group invite - reject group [group_name]\n"
                "To list your groups - my groups\n"
                "To send group text - group txt [group_name] {your message}\n"
                "To send file over TCP - send file [client] [file_path]\n"
                "To end one private chat - end private [client]\n"
                "To exit chat77 :(- exit"
            )
            return True
        else:
            print(message)

# This is the function that handles receiving messages from the server and printing them to the console, including handling private chat requests and connections
def client_receive():
    global private_partners, pending_requesters, groups, pending_group_invites

    while True:
        try:
            message = client.recv(1024).decode()

            if message.startswith("PRIVATE_REQUEST_FROM:"):
                requester = message.split(":", 1)[1]
                pending_requesters.add(requester)
                print(f"Private request from {requester}. Type: accept connection {requester} or reject connection {requester}")
                continue

            if message.startswith("PRIVATE_CONNECTED:"):
                partner = message.split(":", 1)[1]
                private_partners.add(partner)
                pending_requesters.discard(partner)
                print(f"Private chat connected with {partner}. Use: private txt {partner} {{your message}}")
                continue

            if message.startswith("PRIVATE_REJECTED:"):
                rejected_by = message.split(":", 1)[1]
                pending_requesters.discard(rejected_by)
                print(f"Private request rejected by {rejected_by}")
                continue

            if message.startswith("PRIVATE_ENDED:"):
                parts = message.split(":", 2)
                ended_by = parts[1] if len(parts) > 1 else "unknown"
                reason = parts[2] if len(parts) > 2 else "ended"
                private_partners.discard(ended_by)
                print(f"Private chat with {ended_by} ended ({reason})")
                continue

            if message.startswith("GROUP_INVITE:"):
                parts = message.split(":", 2)
                if len(parts) == 3:
                    group_name = parts[1]
                    invited_by = parts[2]
                    pending_group_invites.add(group_name)
                    print(f"Group invite to '{group_name}' from {invited_by}. Type: accept group {group_name} or reject group {group_name}")
                continue

            if message.startswith("GROUP_JOINED:"):
                group_name = message.split(":", 1)[1]
                groups.add(group_name)
                pending_group_invites.discard(group_name)
                print(f"You joined group: {group_name}")
                continue

            if message.startswith("FILE_START_FROM|"):
                parts = message.split("|", 4)
                if len(parts) != 5:
                    continue
                sender, filename, size_str, transfer_id = parts[1], parts[2], parts[3], parts[4]
                incoming_transfers[transfer_id] = {
                    "sender": sender,
                    "filename": safe_filename(filename),
                    "size": int(size_str) if size_str.isdigit() else 0,
                    "chunks": {}
                }
                print(f"Incoming file from {sender}: {filename}")
                continue

            if message.startswith("FILE_CHUNK_FROM|"):
                parts = message.split("|", 4)
                if len(parts) != 5:
                    continue
                transfer_id = parts[2]
                seq_str = parts[3]
                if transfer_id not in incoming_transfers or not seq_str.isdigit():
                    continue
                try:
                    chunk_data = base64.b64decode(parts[4].encode())
                except:
                    continue
                incoming_transfers[transfer_id]["chunks"][int(seq_str)] = chunk_data
                continue

            if message.startswith("FILE_END_FROM|"):
                parts = message.split("|", 3)
                if len(parts) != 4:
                    continue
                sender = parts[1]
                transfer_id = parts[2]
                total_chunks_str = parts[3]
                if not total_chunks_str.isdigit():
                    continue
                finalize_incoming_transfer(sender, transfer_id, int(total_chunks_str))
                continue

            print(message)
        except:
            print("Connection closed")
            client.close()
            break

# This is the function that handles sending messages to the server based on user input, including broadcasting messages, sending private messages, and handling connection requests
def client_send():
    global private_partners, groups
    while True:
        text = input("")
        lowered = text.lower().strip()

        if text.lower() == 'exit':
            client.send('exit'.encode())
            try:
                client.shutdown(socket.SHUT_RDWR)
            except:
                pass
            client.close()
            try:
                beep_socket.close()
            except:
                pass
            break

        if lowered == 'online clients':
            client.send('online clients'.encode())
            continue

        if lowered.startswith('create group '):
            group_name = text[len('create group '):].strip()
            if not group_name:
                print("Usage: create group [group_name]")
                continue
            client.send(f'create group {group_name}'.encode())
            continue

        if lowered.startswith('invite group '):
            payload = text[len('invite group '):].strip()
            parts = payload.split(' ', 1)
            if len(parts) < 2:
                print("Usage: invite group [group_name] [client]")
                continue
            group_name, target = parts[0].strip(), parts[1].strip()
            client.send(f'invite group {group_name} {target}'.encode())
            continue

        if lowered.startswith('accept group '):
            group_name = text[len('accept group '):].strip()
            if not group_name:
                print("Usage: accept group [group_name]")
                continue
            client.send(f'accept group {group_name}'.encode())
            continue

        if lowered.startswith('reject group '):
            group_name = text[len('reject group '):].strip()
            if not group_name:
                print("Usage: reject group [group_name]")
                continue
            client.send(f'reject group {group_name}'.encode())
            continue

        if lowered == 'my groups':
            if groups:
                print(f"My groups: {', '.join(sorted(groups))}")
            else:
                print("My groups: none")
            client.send('my groups'.encode())
            continue

        if lowered.startswith('group txt '):
            payload = text[len('group txt '):].strip()
            parts = payload.split(' ', 1)
            if len(parts) < 2:
                print("Usage: group txt [group_name] [message]")
                continue
            group_name, group_message = parts[0].strip(), parts[1].strip()
            if not group_message:
                print("Group message cannot be empty")
                continue
            client.send(f'group txt {group_name} {group_message}'.encode())
            continue

        if text.startswith('connect to '):
            target = text[11:].strip()
            if not target:
                print("Usage: connect to [client]")
                continue
            client.send(f"connect to {target}".encode())
            continue

        if lowered.startswith('accept connection '):
            requester = text[len('accept connection '):].strip()
            if not requester:
                print("Usage: accept connection [client]")
                continue
            client.send(f'accept connection {requester}'.encode())
            continue

        if lowered.startswith('reject connection '):
            requester = text[len('reject connection '):].strip()
            if not requester:
                print("Usage: reject connection [client]")
                continue
            client.send(f'reject connection {requester}'.encode())
            continue

        if lowered == 'my private chats':
            if private_partners:
                print(f"My private chats: {', '.join(sorted(private_partners))}")
            else:
                print("My private chats: none")
            continue

        if lowered.startswith('end private '):
            target = text[len('end private '):].strip()
            if not target:
                print("Usage: end private [client]")
                continue
            client.send(f'end private {target}'.encode())
            continue

        if lowered.startswith('send file '):
            payload = text[len('send file '):].strip()
            parts = payload.split(' ', 1)
            if len(parts) < 2:
                print("Usage: send file [client] [file_path]")
                continue
            target, file_path = parts[0].strip(), parts[1].strip().strip('"')
            if target not in private_partners:
                print(f"No active private chat with {target}. Use: connect to {target}")
                continue
            send_file_via_tcp(target, file_path)
            continue

        if lowered.startswith('bdct txt '):
            actual_text = text[9:].strip()
            if not actual_text:
                print("Broadcast message cannot be empty. Use: bdct txt {your message}")
                continue

            message = f'{aliase}: {actual_text}'
            client.send(message.encode())
            continue

        if lowered.startswith('private txt '):
            payload = text[12:].strip()
            if not payload or ' ' not in payload:
                print("Usage: private txt [client] {your message}")
                continue
            target, actual_text = payload.split(' ', 1)
            if target not in private_partners:
                print(f"No active private chat with {target}. Use: my private chats")
                continue
            if not actual_text.strip():
                print("Private message cannot be empty")
                continue
            client.send(f"private txt {target} {actual_text}".encode())
            continue

        print("Invalid command. Use: bdct txt {your message}, online clients, connect to [client], accept connection [client], reject connection [client], my private chats, private txt [client] {your message}, create group [group_name], invite group [group_name] [client], accept group [group_name], reject group [group_name], my groups, group txt [group_name] [message], send file [client] [file_path], end private [client], or exit")

    # Start receive and send threads after authentication is successful
if authenticate():
    register_beep_port()

    beep_thread = threading.Thread(target=beep_receive, daemon=True)
    beep_thread.start()

    receive_thread = threading.Thread(target=client_receive)
    receive_thread.start()

    send_thread = threading.Thread(target=client_send)
    send_thread.start()