import threading
import socket

server_ip = input("Enter server IP address: ")
client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
client.connect((server_ip, 12345))
aliase = ""
private_partner = None

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
            print("User Commands:\nTo broadcast text - bdct txt {your message}\nTo check for online users - online clients\nTo connect with a user - connect to [client]\nTo accept connection from a user - accept connection\nTo reject connection with a user - reject connection\nTo exit chat77 :(- exit")
            return
        else:
            print(message)

# This is the function that handles receiving messages from the server and printing them to the console, including handling private chat requests and connections
def client_receive():
    global private_partner

    while True:
        try:
            message = client.recv(1024).decode()

            if message.startswith("PRIVATE_REQUEST_FROM:"):
                requester = message.split(":", 1)[1]
                print(f"Private request from {requester}. Type: accept connection or reject connection")
                continue

            if message.startswith("PRIVATE_CONNECTED:"):
                private_partner = message.split(":", 1)[1]
                print(f"Private chat connected with {private_partner}. Use: private txt {{your message}}")
                continue

            if message.startswith("PRIVATE_REJECTED:"):
                rejected_by = message.split(":", 1)[1]
                print(f"Private request rejected by {rejected_by}")
                continue

            if message.startswith("PRIVATE_ENDED:"):
                ended_by = message.split(":", 1)[1]
                private_partner = None
                print(f"Private chat ended because {ended_by} disconnected")
                continue

            print(message)
        except:
            print("Connection closed")
            client.close()
            break

# This is the function that handles sending messages to the server based on user input, including broadcasting messages, sending private messages, and handling connection requests
def client_send():
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

        if lowered == 'accept connection':
            client.send('accept connection'.encode())
            continue

        if lowered == 'reject connection':
            client.send('reject connection'.encode())
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
            actual_text = text[12:].strip()
            if not actual_text:
                print("Private message cannot be empty. Use: private txt {your message}")
                continue
            client.send(f"private txt {actual_text}".encode())
            continue

        if private_partner is not None:
            client.send(f"private txt {text}".encode())
        else:
            print("Invalid command. Use: bdct txt {your message}, online clients, connect to [client], accept connection, reject connection, private txt {your message}, or exit")


authenticate()

# Start the receive and send threads after authentication is successful
receive_thread = threading.Thread(target=client_receive)
receive_thread.start()

send_thread = threading.Thread(target=client_send)
send_thread.start()