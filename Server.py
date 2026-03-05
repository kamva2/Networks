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

#Have to broadcast a message for the chat box or clients that are connected
def broadcast(message, sender=None):
    for client in clients:
        if client != sender:
            client.send(message)


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

    broadcast(f"{aliase} has left the chatroom".encode())
    database.record_logout(aliase)


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
