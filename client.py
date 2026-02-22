import threading
import socket

aliase = input("Enter aliase name: ")
client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
client.connect(('127.0.0.1', 24680))

# handle receiving messages

def client_receive():
    while True:
        try:
            message = client.recv(1024).decode()
            if message == 'aliase?':
                client.send(aliase.encode())
            else:
                print(message)
        except:
            print("An error occurred!")
            client.close()
            break

# handle sending messages
def client_send():
    while True:
        message = f'{aliase}: {input("")}'
        client.send(message.encode())
        if message.lower() == 'exit':
            client.close()
            break
        else:
            client.send(message.encode())

receive_thread = threading.Thread(target=client_receive)
receive_thread.start()

send_thread = threading.Thread(target=client_send)
send_thread.start()