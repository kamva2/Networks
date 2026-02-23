import socket
import threading

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

# Handling the movements of clients in the chatbox
def handle_client(client):

    while True:
        try:
            message = client.recv(1024)
            broadcast(message, sender=client)
        except:
            index = clients.index(client)
            clients.remove(client)
            client.close()
            aliase = aliases[index]
            broadcast(f"{aliase} has left the chatroom".encode())
            aliases.remove(aliase)
            break

# This is the main function that recieves the client's connection
def receive():
    while True:
        print("Server is running and listening...")
        client,address = server.accept()

        print(f"connection is established with {str(address)}")
        client.send("aliase?".encode())
        aliase = client.recv(1024)
        aliases.append(aliase)
        clients.append(client)
        print(f"The aliase of this client is {aliase}".encode())

        broadcast(f"{aliase} has connected to the chatroom".encode())
        client.send("you are now connected".encode())

        #Then for this program to support multiple clients we have to introduce multi-threading
        thread = threading.Thread(target=handle_client, args=(client,))
        thread.start()
receive()
