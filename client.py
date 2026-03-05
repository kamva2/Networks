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
            print("Use: bdct txt {your message} to broadcast, online clients to list users, exit to leave.")
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
        if text.lower() == 'exit':
            client.send('exit'.encode())
            try:
                client.shutdown(socket.SHUT_RDWR)
            except:
                pass
            client.close()
            break

        if text.lower() == 'online clients':
            client.send('online clients'.encode())
            continue

        if text.lower().startswith('bdct txt '):
            actual_text = text[9:].strip()
            if not actual_text:
                print("Broadcast message cannot be empty. Use: bdct txt {your message}")
                continue

            message = f'{aliase}: {actual_text}'
            client.send(message.encode())
        else:
            print("Invalid command. Use: bdct txt {your message}, online clients, or exit")


authenticate()

receive_thread = threading.Thread(target=client_receive)
receive_thread.start()

send_thread = threading.Thread(target=client_send)
send_thread.start()