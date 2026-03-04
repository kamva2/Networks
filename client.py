import threading
import socket

server_ip = input("Enter server IP address: ")
client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
client.connect((server_ip, 12345))
aliase = ""


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
            print("Authentication successful.")
            return
        else:
            print(message)

# handle receiving messages

def client_receive():
    while True:
        try:
            message = client.recv(1024).decode()
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
        if text.lower() == 'exit':
            client.send(message.encode())
            client.close()
            break
        client.send(message.encode())


authenticate()

receive_thread = threading.Thread(target=client_receive)
receive_thread.start()

send_thread = threading.Thread(target=client_send)
send_thread.start()