import socket
import threading
import database

host = '0.0.0.0'
port = 12345

server = socket.socket(socket.AF_INET,socket.SOCK_STREAM)
server.bind((host,port))
server.listen()

#We keeping track of people who have connected to the server with their aliase and the port
clients = []
aliases = []
pending_requests = {}
private_partners = {}

#Have to broadcast a message for the chat box or clients that are connected
def broadcast(message, sender=None):
    for client in clients:
        if client != sender:
            client.send(message)


def get_client_by_alias(aliase):
    if aliase not in aliases:
        return None
    index = aliases.index(aliase)
    return clients[index]


def send_to_alias(aliase, message):
    target_client = get_client_by_alias(aliase)
    if target_client is None:
        return False
    try:
        target_client.send(message.encode())
        return True
    except:
        return False


def end_private_connection(aliase):
    if aliase not in private_partners:
        return

    partner = private_partners.pop(aliase)
    if partner in private_partners and private_partners[partner] == aliase:
        private_partners.pop(partner)
        send_to_alias(partner, f"PRIVATE_ENDED:{aliase}")


def cleanup_pending_requests(aliase):
    if aliase in pending_requests:
        requester = pending_requests.pop(aliase)
        send_to_alias(requester, f"INFO: {aliase} is no longer available for private chat")

    targets_to_remove = []
    for target, requester in pending_requests.items():
        if requester == aliase:
            targets_to_remove.append(target)

    for target in targets_to_remove:
        pending_requests.pop(target, None)


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

    broadcast(f"{aliase} has left the chatroom".encode())
    database.record_logout(aliase)


def handle_connect_request(aliase, text):
    requested_alias = text[len('connect to '):].strip()

    if not requested_alias:
        return "INFO: Usage -> connect to [client]"

    if requested_alias == aliase:
        return "INFO: You cannot connect to yourself"

    if requested_alias not in aliases:
        return f"INFO: {requested_alias} is not online"

    if aliase in private_partners:
        return "INFO: You are already in a private chat"

    if requested_alias in private_partners:
        return f"INFO: {requested_alias} is already in a private chat"

    if requested_alias in pending_requests:
        return f"INFO: {requested_alias} already has a pending request"

    pending_requests[requested_alias] = aliase
    send_to_alias(requested_alias, f"PRIVATE_REQUEST_FROM:{aliase}")
    return f"INFO: Connection request sent to {requested_alias}"


def handle_accept_request(aliase):
    if aliase not in pending_requests:
        return "INFO: You have no pending private request"

    requester = pending_requests.pop(aliase)
    if requester not in aliases:
        return "INFO: Requester is no longer online"

    if aliase in private_partners or requester in private_partners:
        return "INFO: Either you or requester is already in a private chat"

    private_partners[aliase] = requester
    private_partners[requester] = aliase
    send_to_alias(requester, f"PRIVATE_CONNECTED:{aliase}")
    return f"PRIVATE_CONNECTED:{requester}"


def handle_reject_request(aliase):
    if aliase not in pending_requests:
        return "INFO: You have no pending private request"

    requester = pending_requests.pop(aliase)
    send_to_alias(requester, f"PRIVATE_REJECTED:{aliase}")
    return f"INFO: Rejected private request from {requester}"


def authenticate_client(client):
    while True:
        client.send("Authorise MODE? (REGISTER/LOGIN)".encode())
        mode = client.recv(1024).decode().strip().upper()

        if mode not in ("REGISTER", "LOGIN"):
            client.send("ERROR: Invalid auth mode".encode())
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
def handle_client(client, aliase):

    while True:
        try:
            message = client.recv(1024)
            if not message:
                remove_client(client)
                break

            text = message.decode(errors='ignore').strip().lower()
            if text == 'exit' or text == f'{aliase}: exit'.lower():
                remove_client(client)
                break

            if text == 'online clients':
                online_list = ', '.join(aliases) if aliases else 'No clients online.'
                client.send(f"Online clients: {online_list}".encode())
                continue

            if text.startswith('connect to '):
                response = handle_connect_request(aliase, text)
                client.send(response.encode())
                continue

            if text == 'accept connection':
                response = handle_accept_request(aliase)
                client.send(response.encode())
                continue

            if text == 'reject connection':
                response = handle_reject_request(aliase)
                client.send(response.encode())
                continue

            if text.startswith('private txt '):
                private_text = message.decode(errors='ignore')[12:].strip()
                if aliase not in private_partners:
                    client.send("INFO: You are not in a private chat".encode())
                    continue
                if not private_text:
                    client.send("INFO: Private message cannot be empty".encode())
                    continue

                partner = private_partners[aliase]
                send_to_alias(partner, f"[Private] {aliase}: {private_text}")
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
        thread = threading.Thread(target=handle_client, args=(client, aliase))
        thread.start()
receive()
