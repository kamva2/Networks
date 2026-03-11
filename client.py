import threading
import socket
import os
import base64
import uuid

server_ip = input("Enter server IP address: ")
client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
client.connect((server_ip, 12345))
aliase = ""
private_partners = set()
pending_requesters = set()
udp_peers = {}
incoming_transfers = {}

udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
udp_socket.bind(("", 0))
udp_port = udp_socket.getsockname()[1]

# This is the function that notifies the server of the client's UDP port after successful authentication, so that the server can facilitate UDP peer discovery for private file transfers
def notify_server_udp_port():
    try:
        client.send(f"UDP_PORT:{udp_port}".encode())
    except:
        print("Failed to register UDP port with server")

# Keep only basename to prevent writing outside project folders.
def safe_filename(name):
    
    return os.path.basename(name)

#Load the client connection database from JSON file, or create a new one if it doesn't exist
def ensure_download_dir():
    download_dir = os.path.join(os.getcwd(), "downloads")
    os.makedirs(download_dir, exist_ok=True)
    return download_dir

# This is the function that handles receiving file chunks over UDP and reconstructing the file once all chunks are received, saving it to the downloads directory
def udp_receive():
    while True:
        try:
            payload, _ = udp_socket.recvfrom(65535)
            text = payload.decode(errors='ignore')

            if text.startswith("FILE_START|"):
                parts = text.split("|", 4)
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

            if text.startswith("FILE_CHUNK|"):
                parts = text.split("|", 4)
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

            if text.startswith("FILE_END|"):
                parts = text.split("|", 4)
                if len(parts) < 4:
                    continue
                sender = parts[1]
                transfer_id = parts[2]
                total_chunks_str = parts[3]
                transfer = incoming_transfers.get(transfer_id)
                if transfer is None or not total_chunks_str.isdigit():
                    continue

                total_chunks = int(total_chunks_str)
                chunks = transfer["chunks"]
                missing = [idx for idx in range(total_chunks) if idx not in chunks]
                if missing:
                    print(f"File from {sender} incomplete. Missing {len(missing)} chunks")
                    incoming_transfers.pop(transfer_id, None)
                    continue

                file_bytes = b"".join(chunks[idx] for idx in range(total_chunks))
                download_dir = ensure_download_dir()
                out_path = os.path.join(download_dir, transfer["filename"])
                with open(out_path, "wb") as out_file:
                    out_file.write(file_bytes)

                print(f"File received from {sender}: {out_path}")
                incoming_transfers.pop(transfer_id, None)
                continue
        except:
            break

# This is the function that sends a file to a target client over UDP by splitting it into chunks and sending start, chunk, and end messages to the target's UDP endpoint
def send_file_via_udp(target, file_path):
    endpoint = udp_peers.get(target)
    if endpoint is None:
        print(f"No UDP peer for {target}. Run: udp connect {target}")
        return

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
    chunk_size = 1000
    total_chunks = (len(data) + chunk_size - 1) // chunk_size

    try:
        udp_socket.sendto(f"FILE_START|{aliase}|{filename}|{len(data)}|{transfer_id}".encode(), endpoint)
        for idx in range(total_chunks):
            chunk = data[idx * chunk_size:(idx + 1) * chunk_size]
            chunk_b64 = base64.b64encode(chunk).decode()
            udp_socket.sendto(f"FILE_CHUNK|{aliase}|{transfer_id}|{idx}|{chunk_b64}".encode(), endpoint)
        udp_socket.sendto(f"FILE_END|{aliase}|{transfer_id}|{total_chunks}".encode(), endpoint)
        print(f"File sent to {target}: {filename}")
    except Exception as ex:
        print(f"Failed to send file over UDP: {ex}")

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
                "To link UDP with private partner - udp connect [client]\n"
                "To send file over UDP - send file [client] [file_path]\n"
                "To end one private chat - end private [client]\n"
                "To exit chat77 :(- exit"
            )
            notify_server_udp_port()
            return True
        else:
            print(message)

# This is the function that handles receiving messages from the server and printing them to the console, including handling private chat requests and connections
def client_receive():
    global private_partners, pending_requesters

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
                udp_peers.pop(ended_by, None)
                print(f"Private chat with {ended_by} ended ({reason})")
                continue

            if message.startswith("UDP_PEER:"):
                parts = message.split(":", 3)
                if len(parts) == 4 and parts[3].isdigit():
                    peer_alias = parts[1]
                    peer_ip = parts[2]
                    peer_port = int(parts[3])
                    udp_peers[peer_alias] = (peer_ip, peer_port)
                    print(f"UDP peer ready for {peer_alias} at {peer_ip}:{peer_port}")
                continue

            print(message)
        except:
            print("Connection closed")
            client.close()
            break

# This is the function that handles sending messages to the server based on user input, including broadcasting messages, sending private messages, and handling connection requests
def client_send():
    global private_partners
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
            break

        if lowered == 'online clients':
            client.send('online clients'.encode())
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

        if lowered.startswith('udp connect '):
            target = text[len('udp connect '):].strip()
            if not target:
                print("Usage: udp connect [client]")
                continue
            client.send(f'udp connect {target}'.encode())
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
            send_file_via_udp(target, file_path)
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

        print("Invalid command. Use: bdct txt {your message}, online clients, connect to [client], accept connection [client], reject connection [client], my private chats, private txt [client] {your message}, end private [client], or exit")

# Start the udp, receive and send threads after authentication is successful
if authenticate():
    udp_thread = threading.Thread(target=udp_receive, daemon=True)
    udp_thread.start()

    
    receive_thread = threading.Thread(target=client_receive)
    receive_thread.start()

    send_thread = threading.Thread(target=client_send)
    send_thread.start()