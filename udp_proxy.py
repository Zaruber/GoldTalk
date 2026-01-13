import socket
import sys

# Configuration
LOCAL_PORT = 27016        # Port to listen on (connect your game here: connect localhost:27016)
REMOTE_IP = "93.157.172.40" # Target Server IP (from your logs)
REMOTE_PORT = 27015       # Target Server Port

def main():
    # Create UDP socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('0.0.0.0', LOCAL_PORT))
    
    print(f"[*] UDP Proxy listening on 0.0.0.0:{LOCAL_PORT}")
    print(f"[*] Forwarding to {REMOTE_IP}:{REMOTE_PORT}")
    print(f"[*] INSTRUCTION: Open your CS 1.6 console (~) and type: connect 127.0.0.1:{LOCAL_PORT}")
    
    client_addr = None
    
    while True:
        try:
            data, addr = sock.recvfrom(65535)
            
            if addr == client_addr:
                # Direction: Client -> Server
                # Print nicely for us to copy-paste into our python script
                log_msg = f"\n[CLIENT -> SERVER] ({len(data)} bytes)\nHex: {data.hex()}\nStr: {data.decode('latin-1', errors='replace')}\n"
                print(log_msg)
                with open("proxy.log", "a") as f:
                    f.write(log_msg)
                
                sock.sendto(data, (REMOTE_IP, REMOTE_PORT))
                
            else:
                # If we received from someone who is NOT the known client, check if it's the server
                if addr[0] == socket.gethostbyname(REMOTE_IP) and addr[1] == REMOTE_PORT:
                    # Direction: Server -> Client
                    if client_addr:
                        sock.sendto(data, client_addr)
                        # Log server responses to debug rejection
                        log_msg = f"\n[SERVER -> CLIENT] ({len(data)} bytes)\nHex: {data.hex()}\nStr: {data.decode('latin-1', errors='replace')}\n"
                        print(log_msg)
                        with open("proxy.log", "a") as f:
                            f.write(log_msg)
                else:
                    # New Client
                    client_addr = addr
                    print(f"[*] New Client connected: {client_addr}")
                    
                    # Forward packet
                    log_msg = f"\n[CLIENT -> SERVER] (First Packet) ({len(data)} bytes)\nHex: {data.hex()}\nStr: {data.decode('latin-1', errors='replace')}\n"
                    print(log_msg)
                    with open("proxy.log", "a") as f:
                        f.write(log_msg)
                    
                    sock.sendto(data, (REMOTE_IP, REMOTE_PORT))

    except KeyboardInterrupt:
        print("\nExiting...")
        break
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
