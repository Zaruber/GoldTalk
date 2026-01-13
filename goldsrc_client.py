import asyncio
import socket
import struct
import time
import logging

logger = logging.getLogger("GoldSrcClient")

APP_ID = 10  # Counter-Strike 1.6
PROTO_VERSION = 48

APP_ID = 10
PROTO_VERSION = 48

# Simple function to strip colors from CS 1.6 chat (basic heuristic)
def clean_chat_text(text):
    return text.replace('\x01', '').replace('\x03', '').replace('\x04', '')

class GoldSrcClient:
    def __init__(self, host, port, nickname, on_chat_message=None, on_player_list=None):
        self.host = host
        self.port = port
        self.nickname = nickname
        self.on_chat_message = on_chat_message # Async callback
        self.on_player_list = on_player_list   # Async callback
        
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setblocking(False)
        # Connect UDP socket to remote host to allow using sock_recv and filter noise
        try:
            self.sock.connect((host, port))
        except Exception as e:
            logger.error(f"Socket connect error: {e}")

        self.is_connected = False
        self.challenge = 0
        self.loop = asyncio.get_event_loop()
        self.keep_alive_task = None
        self.read_task = None

    async def connect(self):
        logger.info(f"Connecting to {self.host}:{self.port} as {self.nickname}...")
        
        # 1. Get Challenge
        # Since connected, use send() instead of sendto, or sendall()
        # But sendto works on connected sockets in Python too usually, ignoring addr if connect called?
        # Safe to use send()
        self.send_packet(b'\xff\xff\xff\xffgetchallenge steam')
        
        # We start reading immediately to handle the response
        self.read_task = self.loop.create_task(self.read_loop())
        
    def send_packet(self, data):
        try:
            self.sock.send(data)
        except Exception as e:
            logger.error(f"Send error: {e}")

    async def read_loop(self):
        logger.info("Started UDP read loop")
        while True:
            try:
                # sock_recv returns bytes only
                data = await self.loop.sock_recv(self.sock, 4096)
                # Since we connected the socket, we only get packets from host:port
                self.handle_packet(data)
            except Exception as e:
                logger.error(f"Read error: {e}")
                await asyncio.sleep(0.1)

    def handle_packet(self, data):
        # Header check
        if data.startswith(b'\xff\xff\xff\xff'):
            # Connectionless Packet
            payload = data[4:]
            header = payload[0:1]
            content = payload[1:]

            if header == b'A': # S2C_CHALLENGE (0x41)
                # This header is used for BOTH connection handshake AND A2S query challenges.
                # A2S Challenge is usually exactly 4 bytes.
                # Connection Challenge is usually an ASCII string with info.
                
                if len(content) == 4:
                    # A2S_PLAYER Challenge
                    challenge = content[:4]
                    logger.info(f"Got A2S Challenge: {challenge.hex()}")
                    msg = b'\xff\xff\xff\xff\x55' + challenge
                    self.send_packet(msg)
                else:
                    # Connection Challenge
                    try:
                        # expected format: "A00000000 <challenge> <auth>"
                        parts = content.split(b' ')
                        if len(parts) > 1:
                            challenge_str = parts[1]
                            self.challenge = int(challenge_str)
                            logger.info(f"Got Connect Challenge: {self.challenge}")
                            self.perform_connect()
                    except Exception as e:
                        logger.error(f"Failed to parse connect challenge: {e}")

            elif header == b'D': # A2S_PLAYER Response
                self.parse_players(content)
                  
        else:
            # NetChan Packet
            # Very basic parsing. Real packets are compressed/encrypted/sequenced.
            # Without full NetChan (Sequence nums), we can't reliably parse the stream.
            # However, uncompressed messages might be visible.
            try:
                # Basic string search for chat messages since we lack full protocol implementation
                # CS 1.6 chat usually comes in SVC_PRINT or SVC_SAYTEXT
                decoded = data.decode('latin-1', errors='ignore')
                
                # Heuristic: Look for typical chat patterns or just log readable strings
                # This is a HACK for MVP because implementing GoldSrc NetChan + Huffman + Delta is huge.
                # Use this to verify we receive *something*.
                
                if "Console:" in decoded or " : " in decoded:
                     # Clean up non-printable
                    clean = "".join(c for c in decoded if c.isprintable())
                    if len(clean) > 5:
                         if self.on_chat_message:
                            asyncio.create_task(self.on_chat_message("Game", clean, "game"))

            except Exception as e:
                pass

    def perform_connect(self):
        # connect <proto> <authproto> <challenge> <challenge_val>
        # "connect 48 3 123456789 \"\\prot\\3\\unique\\-1\\raw\\...\""
        
        # UserInfo string
        user_info = (
            f"\\name\\{self.nickname}"
            f"\\model\\gordon"
            f"\\topcolor\\30\\bottomcolor\\6"
            f"\\rate\\25000\\cl_updaterate\\101\\cl_lw\\1\\cl_lc\\1"
            f"\\can_voice_record\\1"  # Tell server we have voice
        )
        
        cmd = f'connect {PROTO_VERSION} {self.challenge} "{user_info}"'
        packet = b'\xff\xff\xff\xff' + cmd.encode('ascii')
        logger.info(f"Sending connect: {cmd}")
        self.send_packet(packet)
        
        # Also need to send "new" command shortly after?
        # Usually client sends:
        # 1. getchallenge
        # 2. connect ...
        # 3. Connection accepted -> Server sends "client_connect"
        # 4. Client sends "new" (ready to enter world)

    async def keep_alive(self):
        logger.info("Starting KeepAlive task")
        while self.is_connected:
            await asyncio.sleep(5) 
            
    async def poll_players_loop(self):
        # Deprecated: usage moved to app.py with CS16ServerParser
        pass

    def parse_players(self, content):
        try:
            # Format: NumPlayers (Byte) + Loop [ Index(Byte), Name(Str), Kills(Long), Time(Float) ]
            num_players = content[0]
            ptr = 1
            players = []
            
            for _ in range(num_players):
                if ptr >= len(content): break
                idx = content[ptr]
                ptr += 1
                
                # Parse Name (Null terminated)
                name_end = content.find(b'\x00', ptr)
                if name_end == -1: break
                
                name_bytes = content[ptr:name_end]
                name = name_bytes.decode('utf-8', errors='ignore')
                ptr = name_end + 1
                
                # Kills (4 bytes LE)
                if ptr + 4 > len(content): break
                kills = struct.unpack('<l', content[ptr:ptr+4])[0]
                ptr += 4
                
                # Time (4 bytes float)
                if ptr + 4 > len(content): break
                time_val = struct.unpack('<f', content[ptr:ptr+4])[0]
                ptr += 4
                
                players.append({"name": name, "score": kills, "time": int(time_val)})
            
            logger.info(f"Received Player List: {len(players)} players online.")
            for p in players:
                logger.info(f" - {p['name']} (Frags: {p['score']})")

            # Send to web
            if self.on_player_list:
                asyncio.create_task(self.on_player_list(players))
                
        except Exception as e:
            logger.error(f"Error parsing players: {e}")

    def close(self):
        if self.read_task:
            self.read_task.cancel()
        if self.keep_alive_task:
            self.keep_alive_task.cancel()
        self.sock.close()
