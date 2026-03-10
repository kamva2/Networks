import threading
import socket

server_ip = input("Enter server IP address: ")
client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
client.connect((server_ip, 12345))
aliase = ""
private_partners = set()
pending_requesters = set()

# This is the function that handles the authentication process with the server, including registering or logging in, and setting the aliase for the client
def authenticate():
    global aliase

    while True:
        try:
            message = client.recv(1024).decode()
        except:
            print("An error occurred during authentication!")
            client.close()
            return

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
        elif message == "AUTH_SUCCESS":
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
                "To end one private chat - end private [client]\n"
                "To exit chat77 :(- exit"
            )
            return
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
                print(f"Private chat with {ended_by} ended ({reason})")
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


authenticate()

# Start the receive and send threads after authentication is successful
receive_thread = threading.Thread(target=client_receive)
receive_thread.start()

send_thread = threading.Thread(target=client_send)
send_thread.start()