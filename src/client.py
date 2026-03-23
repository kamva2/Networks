import threading
import socket
import os
import base64
import uuid

server_ip = input("Enter server IP address: ").strip()


client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
client.connect((server_ip, 22081))

# UDP socket for receiving beep notifications
beep_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
beep_socket.bind(("", 0))
beep_port = beep_socket.getsockname()[1]

aliase = ""
private_partners = set()
pending_requesters = set()
groups = set()
pending_group_invites = set()
incoming_transfers = {}
client_buffer = b""
running = True

# Function to send a text message to the server, ensuring it ends with a newline character and handling any exceptions that may occur during sending
def send_packet(text):
    try:
        client.sendall((text + "\n").encode())
        return True
    except:
        return False

# Function to receive a line of text from the server, handling buffering and partial messages. It returns the line as a decoded string without the trailing newline character, or None if the connection is closed.
def recv_line():
    global client_buffer
    while True:
        if b"\n" in client_buffer:
            line, rest = client_buffer.split(b"\n", 1)
            client_buffer = rest
            return line.decode(errors="ignore").rstrip("\r")

        chunk = client.recv(4096)
        if not chunk:
            return None
        client_buffer += chunk

# This function registers the UDP port for receiving beep notifications from the server, so that when another user sends a beep to this client, the server knows where to forward it.
def register_beep_port():
    if not send_packet(f"BEEP_UDP_PORT:{beep_port}"):
        print("Failed to register UDP beep port")

# This function runs in a separate thread and listens for incoming UDP messages on the beep socket. When it receives a message that starts with "BEEP:", it parses the sender and channel information and prints a notification to the console.
def beep_receive():
    while True:
        try:
            payload, _ = beep_socket.recvfrom(4096)
            text = payload.decode(errors="ignore")
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

# Load the client connection database from JSON file, returning a dictionary with "users" and "connections" keys. If the file does not exist or is invalid, it returns an empty database structure.
def safe_filename(name):
    return os.path.basename(name)

# This function ensures that the "downloads" directory exists in the current working directory and returns its path. This is where incoming files will be saved.
def ensure_download_dir():
    download_dir = os.path.join(os.getcwd(), "downloads")
    os.makedirs(download_dir, exist_ok=True)
    return download_dir

# This function finalizes an incoming file transfer by checking if all chunks have been received, reconstructing the file from the chunks, and saving it to the downloads directory. 
# If any chunks are missing, it discards the transfer and prints a message indicating that the file is incomplete.
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

    base_name, extension = os.path.splitext(out_path)
    counter = 1
    while os.path.exists(out_path):
        out_path = f"{base_name}_{counter}{extension}"
        counter += 1

    try:
        with open(out_path, "wb") as out_file:
            out_file.write(file_bytes)
        print(f"File received from {sender}: {out_path}")
    except Exception as ex:
        print(f"Failed to save file from {sender}: {ex}")

    incoming_transfers.pop(transfer_id, None)

# This function sends a file to a target client over TCP by first sending a FILE_START packet with the file metadata, then sending the file in base64-encoded chunks, and finally sending a FILE_END packet to indicate completion. It handles errors such as file not found, read failures, and send failures, printing appropriate messages for each case.
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
        if not send_packet(f"FILE_START|{target}|{filename}|{len(data)}|{transfer_id}"):
            print("Failed to send file start packet")
            return

        for idx in range(total_chunks):
            chunk = data[idx * chunk_size:(idx + 1) * chunk_size]
            chunk_b64 = base64.b64encode(chunk).decode()
            if not send_packet(f"FILE_CHUNK|{target}|{transfer_id}|{idx}|{chunk_b64}"):
                print("Failed during file transfer")
                return

        if not send_packet(f"FILE_END|{target}|{transfer_id}|{total_chunks}"):
            print("Failed to send file end packet")
            return

        print(f"File sent to {target}: {filename}")
    except Exception as ex:
        print(f"Failed to send file over TCP: {ex}")

# This function handles the authentication process for the client, including registration and login.
def authenticate():
    global aliase

    while True:
        try:
            message = recv_line()
            if message is None:
                print("Connection closed during authentication.")
                client.close()
                return False
        except:
            print("An error occurred during authentication!")
            client.close()
            return False

        if message.startswith("Authorise MODE?"):
            mode = input("Choose auth mode (REGISTER/LOGIN): ").strip().upper()
            if not send_packet(mode):
                print("Failed to send authentication mode.")
                return False

        elif message == "ALIAS?":
            aliase = input("Enter aliase name: ").strip()
            if not send_packet(aliase):
                print("Failed to send alias.")
                return False

        elif message == "PASSWORD?":
            password = input("Enter password: ").strip()
            if not send_packet(password):
                print("Failed to send password.")
                return False

        elif message.startswith("ERROR:") or message.startswith("INFO:") or message == "This alias is already logged in":
            print(message)

        elif message == "Registration successful. You can login now.":
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

# The following functions interact with the client connection database to register new users, authenticate existing users, check if a user exists, and record login/logout events with timestamps.
# They handle the necessary data transformations and ensure that the database is updated accordingly.
def client_receive():
    global private_partners, pending_requesters, groups, pending_group_invites, running

    while running:
        try:
            message = recv_line()
            if message is None:
                print("Connection closed")
                try:
                    client.close()
                except:
                    pass
                break

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

            if message.startswith("Groups: "):
                print(message)
                continue

            if message.startswith("Private chats: "):
                print(message)
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
            try:
                client.close()
            except:
                pass
            break

# Load the client connection database from JSON file, returning a dictionary with "users" and "connections" keys. If the file does not exist or is invalid, it returns an empty database structure.
def client_send():
    global private_partners, groups, running

    while True:
        try:
            text = input("")
        except EOFError:
            text = "exit"

        lowered = text.lower().strip()

        if lowered == 'exit':
            send_packet('exit')
            running = False
            try:
                client.shutdown(socket.SHUT_RDWR)
            except:
                pass
            try:
                client.close()
            except:
                pass
            try:
                beep_socket.close()
            except:
                pass
            break

        if lowered == 'online clients':
            send_packet('online clients')
            continue

        if lowered.startswith('create group '):
            group_name = text[len('create group '):].strip()
            if not group_name:
                print("Usage: create group [group_name]")
                continue
            send_packet(f'create group {group_name}')
            continue

        if lowered.startswith('invite group '):
            payload = text[len('invite group '):].strip()
            parts = payload.split(' ', 1)
            if len(parts) < 2:
                print("Usage: invite group [group_name] [client]")
                continue
            group_name, target = parts[0].strip(), parts[1].strip()
            send_packet(f'invite group {group_name} {target}')
            continue

        if lowered.startswith('accept group '):
            group_name = text[len('accept group '):].strip()
            if not group_name:
                print("Usage: accept group [group_name]")
                continue
            send_packet(f'accept group {group_name}')
            continue

        if lowered.startswith('reject group '):
            group_name = text[len('reject group '):].strip()
            if not group_name:
                print("Usage: reject group [group_name]")
                continue
            send_packet(f'reject group {group_name}')
            continue

        if lowered == 'my groups':
            send_packet('my groups')
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
            send_packet(f'group txt {group_name} {group_message}')
            continue

        if lowered.startswith('connect to '):
            target = text[11:].strip()
            if not target:
                print("Usage: connect to [client]")
                continue
            send_packet(f"connect to {target}")
            continue

        if lowered.startswith('accept connection '):
            requester = text[len('accept connection '):].strip()
            if not requester:
                print("Usage: accept connection [client]")
                continue
            send_packet(f'accept connection {requester}')
            continue

        if lowered.startswith('reject connection '):
            requester = text[len('reject connection '):].strip()
            if not requester:
                print("Usage: reject connection [client]")
                continue
            send_packet(f'reject connection {requester}')
            continue

        if lowered == 'my private chats':
            send_packet('my private chats')
            continue

        if lowered.startswith('end private '):
            target = text[len('end private '):].strip()
            if not target:
                print("Usage: end private [client]")
                continue
            send_packet(f'end private {target}')
            continue

        if lowered.startswith('send file '):
            payload = text[len('send file '):].strip()
            parts = payload.split(' ', 1)
            if len(parts) < 2:
                print("Usage: send file [client] [file_path]")
                continue

            target = parts[0].strip()
            file_path = parts[1].strip().strip('"')

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

            send_packet(f'{aliase}: {actual_text}')
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

            send_packet(f"private txt {target} {actual_text}")
            continue

        print("Invalid command. Use: bdct txt {your message}, online clients, connect to [client], accept connection [client], reject connection [client], my private chats, private txt [client] {your message}, create group [group_name], invite group [group_name] [client], accept group [group_name], reject group [group_name], my groups, group txt [group_name] [message], send file [client] [file_path], end private [client], or exit")


if authenticate():
    register_beep_port()

    # Start the threads for receiving beeps and messages from the server, and for sending user input to the server. 
    beep_thread = threading.Thread(target=beep_receive, daemon=True)
    beep_thread.start()

    receive_thread = threading.Thread(target=client_receive, daemon=True)
    receive_thread.start()

    # The main thread will handle user input and sending messages to the server, while the other threads will handle receiving messages and beeps. 
    # The program will continue running until the user types "exit" or the connection is closed.
    send_thread = threading.Thread(target=client_send)
    send_thread.start()
    send_thread.join()