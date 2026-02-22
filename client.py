import threading
import socket

aliase = input("Enter aliase name: ")
server_ip = input("Enter server IP address: ")
client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
client.connect((server_ip, 24680))

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
        text = input("")
        message = f'{aliase}: {text}'
        client.send(message.encode())
        if text.lower() == 'exit':
            client.close()
            break
        else:
            client.send(message.encode())

receive_thread = threading.Thread(target=client_receive)
receive_thread.start()

send_thread = threading.Thread(target=client_send)
send_thread.start()