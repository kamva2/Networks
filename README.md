# Chat77 Networks

## 1. Project Summary

This project is a TCP-based multi-client chatroom written in Python.
It supports:
- User registration and login
- Public (broadcast) messaging
- Listing online clients
- Private chat request/accept/reject flow
- One-to-one private messaging after mutual connection
- Session logging to a JSON "database"

The system is split into 3 main modules:
- Server.py: socket server, command routing, private chat state management
- client.py: terminal client with send/receive threads and command parser
- database.py: JSON persistence for users and connection history

A utility file, WifiAround.py, prints nearby Wi-Fi networks using Windows netsh.

## 2. Repository Structure

- Server.py: main chat server
- client.py: chat client
- database.py: simple JSON persistence layer
- client_connections.json: data store used by database.py
- WifiAround.py: local network scan utility (not required for chat)

## 3. How To Run

## 3.1 Requirements
- Python 3.10+
- Windows, Linux, or macOS for chat features
- Windows specifically if using WifiAround.py ('netsh' command)

## 3.2 Start Server
From project root:

'bash
python Server.py


Server listens on:
- Host: `0.0.0.0`
- Port: `12345`

## 3.3 Start Clients
Open separate terminals (one per client):

bash
python client.py


Each client is prompted for the server IP address.

## 4. Feature Behavior

## 4.1 Authentication
The server starts by sending an authentication prompt sequence:
1. `Authorise MODE? (REGISTER/LOGIN)`
2. `ALIAS?`
3. `PASSWORD?`

If user chooses `REGISTER`, credentials are saved in `client_connections.json` and user must then login.

If user chooses `LOGIN`, credentials are validated against stored users.

After successful login:
- Client is added to online lists (`clients`, `aliases`)
- Login is recorded in JSON with timestamp and socket address
- Other users are notified that this user joined

## 4.2 Public Chat
Users send public text with:
- `bdct txt {message}`

The client formats this as:
- `{alias}: {message}`

Server broadcasts to all connected clients except the sender.

## 4.3 Online User List
Command:
- `online clients`

Server responds with comma-separated aliases currently connected.

## 4.4 Private Chat Flow
Private chat is modeled as a two-step handshake:

1. Request:
- Sender command: `connect to [client]`
- Server records pending request in `pending_requests[target]`
- Target receives: `PRIVATE_REQUEST_FROM:{sender}`

2. Response:
- Accept: `accept connection [client]`
- Reject: `reject connection [client]`

On accept:
- Two-way relation added in `private_partners`
- Both users receive `PRIVATE_CONNECTED:...`

On reject:
- Request removed
- Requester receives `PRIVATE_REJECTED:{target}`

## 4.5 Private Messaging
Once two users are connected privately, sender can run:
- `private txt [client] {message}`

Server checks that a private connection exists, then forwards message to target only.

## 4.6 Ending Private Chats
Command:
- `end private [client]`

Server removes both directions from `private_partners` and notifies both users with:
- `PRIVATE_ENDED:{other}:{reason}`

If a client disconnects, all their active private chats are automatically ended.

## 4.7 Exit and Cleanup
Command:
- `exit`

Server cleanup includes:
- Removing client socket and alias from active lists
- Clearing related pending private requests
- Ending all private partner relations
- Recording logout timestamp in JSON
- Broadcasting leave notification

## 5. Internal State Model (Server)

`Server.py` keeps in-memory state:
- `clients: list[socket]` - active client sockets
- `aliases: list[str]` - parallel list aligned by index with `clients`
- `pending_requests: dict[target_alias, set[requester_alias]]`
- `private_partners: dict[alias, set[connected_aliases]]`

This design makes lookups and cleanup straightforward but assumes list index alignment is always preserved.

## 6. Message/Command Protocol

Client -> Server commands (plain text):
- `online clients`
- `connect to [client]`
- `accept connection [client]`
- `reject connection [client]`
- `my private chats`
- `private txt [client] [message]`
- `end private [client]`
- `exit`
- Any other text from `bdct txt` is sent as `{alias}: {message}` for broadcast

Server -> Client control messages:
- `ERROR: ...`
- `INFO: ...`
- `PRIVATE_REQUEST_FROM:{alias}`
- `PRIVATE_CONNECTED:{alias}`
- `PRIVATE_REJECTED:{alias}`
- `PRIVATE_ENDED:{alias}:{reason}`

## 7. File-By-File Code Explanation

## 7.1 `Server.py`
Main responsibilities:
- Accept incoming TCP connections
- Authenticate users (register/login)
- Route commands
- Manage public and private messaging state
- Persist login/logout events

Important functions:
- `broadcast(message, sender=None)`: sends message to all clients except sender
- `resolve_alias(raw_alias)`: case-insensitive alias matching to active user
- `handle_connect_request(...)`: creates pending private request
- `handle_accept_request(...)`: validates and activates private chat
- `handle_reject_request(...)`: removes pending request and notifies requester
- `handle_private_message(...)`: forwards private message if relation exists
- `remove_client(client)`: central disconnect cleanup routine
- `handle_client(client, alias)`: per-client command loop
- `receive()`: main accept loop, thread spawning

Concurrency model:
- One dedicated thread per client (`threading.Thread`)
- Shared global structures are mutated by multiple threads

## 7.2 `client.py`
Main responsibilities:
- Connect to server over TCP
- Handle interactive authentication prompts
- Read user commands from terminal
- Listen for and display server messages asynchronously

Core flow:
- `authenticate()` handles prompt/response exchange
- `client_receive()` listens for server control messages and updates local sets
- `client_send()` parses user input and sends appropriate command strings

Client-side state:
- `private_partners: set[str]`: known active private chats
- `pending_requesters: set[str]`: pending incoming private requests

## 7.3 `database.py`
Main responsibilities:
- Load/save JSON database file
- Register and authenticate users
- Record login/logout audit trail

Key operations:
- `load_database()` initializes defaults if JSON missing/corrupt
- `register_user(alias, password)` appends to `users`
- `authenticate_user(alias, password)` checks credentials
- `record_login(alias, ip, port)` writes connection start record
- `record_logout(alias)` updates latest open session for alias

Data format in `client_connections.json`:
- `users`: alias/username/password metadata
- `connections`: login/logout records with IP/port/timestamps

## 7.4 `WifiAround.py`
A standalone helper script:
- Runs `netsh wlan show network`
- Decodes and prints output

It is unrelated to chat protocol logic.

## 8. Thought Process Behind The Design

The architecture suggests a progression from assignment requirements toward incremental feature growth:

1. Build a baseline threaded chat server
- Start with TCP sockets and multi-client support via one thread per connection.

2. Add account handling
- Introduce a lightweight persistence layer (`database.py`) using JSON so registration/login survives restarts without introducing external dependencies.

3. Add private messaging safely
- Instead of direct unrestricted private messaging, require explicit consent:
  - request -> accept/reject -> active private link
- This creates a clearer social/permission model and helps avoid accidental direct messages.

4. Track lifecycle events
- Record login and logout timestamps to show connection history, useful for monitoring and demonstration.

5. Keep protocol human-readable
- Text commands and prefixed control messages make debugging easy from terminal clients.

Trade-offs in this approach:
- Simplicity over hard guarantees (in-memory state, no locks)
- Ease of implementation over cryptographic security (plain-text passwords)
- Direct string protocol over structured packets (easy to inspect, but fragile)


## 9. Quick Command Reference

- `bdct txt Hello everyone`
- `online clients`
- `connect to Alice`
- `accept connection Bob`
- `reject connection Bob`
- `my private chats`
- `private txt Alice This is private`
- `end private Alice`
- `exit`

## 10. Educational Value

This project demonstrates important networking concepts:
- TCP server/client socket setup
- Multi-threaded request handling
- Shared state management
- Lightweight persistence patterns
- Protocol design for interactive systems
ReadMe
