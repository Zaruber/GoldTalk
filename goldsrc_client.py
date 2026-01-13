import asyncio
import socket
import struct
import time
import logging

logger = logging.getLogger("GoldSrcClient")

APP_ID = 10  # Counter-Strike 1.6
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
        try:
            self.sock.connect((host, port))
        except Exception as e:
            logger.error(f"Socket connect error: {e}")

        # State
        self.is_connected = False
        self.challenge = 0
        self.connection_step = 0 # 0: Disconnected, 1: Challenged, 2: Connected/New sent
        
        # Async tasks
        self.loop = asyncio.get_event_loop()
        self.keep_alive_task = None
        self.read_task = None
        self.process_task = None
        self.msg_queue = asyncio.Queue()

    async def connect(self):
        logger.info(f"Connecting to {self.host}:{self.port} as {self.nickname}...")
        
        # Step 1: Request Challenge (Add newline as seen in logs)
        self.send_packet(b'\xff\xff\xff\xffgetchallenge steam\n')
        
        self.read_task = self.loop.create_task(self.read_loop())
        # Start KeepAlive immediately
        self.keep_alive_task = self.loop.create_task(self.keep_alive())

    # ... (read_loop/handle_packet remain)

    def perform_connect(self):
        # Based on captured logs:
        # connect <proto> <challenge> "<auth_info>" "<user_info>"
        
        # 1. Auth Info
        # "\prot\3\unique\-1\raw\steam\cdkey\<32chars>"
        import hashlib
        # Generate a semi-random cdkey based on nickname
        cdkey_hash = hashlib.md5(self.nickname.encode()).hexdigest()
        
        auth_info = (
            f"\\prot\\3"
            f"\\unique\\-1"
            f"\\raw\\steam"
            f"\\cdkey\\{cdkey_hash}"
        )

        # 2. User Info
        # "\topcolor\30\bottomcolor\6\rate\25000\cl_updaterate\100\cl_lw\1\cl_lc\1\model\gordon\name\..."
        user_info = (
            f"\\name\\{self.nickname}"
            f"\\model\\gordon"
            f"\\topcolor\\30\\bottomcolor\\6"
            f"\\rate\\25000\\cl_updaterate\\101\\cl_lw\\1\\cl_lc\\1"
            f"\\can_voice_record\\1"
        )
        
        cmd = f'connect {PROTO_VERSION} {self.challenge} "{auth_info}" "{user_info}"'
        packet = b'\xff\xff\xff\xff' + cmd.encode('ascii')
        logger.info(f"Sending connect: {cmd}")
        self.send_packet(packet)

    def send_packet(self, data):
        try:
            logger.info(f"OUT ({len(data)}): {data.hex()}")
            self.sock.send(data)
        except Exception as e:
            logger.error(f"Send error: {e}")

    async def read_loop(self):
        logger.info("Started UDP read loop")
        while True:
            try:
                data = await self.loop.sock_recv(self.sock, 65535)
                logger.info(f"IN ({len(data)}): {data.hex()}")
                self.handle_packet(data)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Read error: {e}")
                await asyncio.sleep(0.1)

    def handle_packet(self, data):
        if len(data) < 5: return

        # Header check
        if data.startswith(b'\xff\xff\xff\xff'):
            # Connectionless Packet (OOB)
            payload = data[4:]
            header = payload[0:1]
            content = payload[1:]

            if header == b'A': # S2C_CHALLENGE (0x41)
                # "A00000000 <challenge> <auth>"
                try:
                    parts = content.split(b' ')
                    if len(parts) > 1:
                        challenge_str = parts[1]
                        self.challenge = int(challenge_str)
                        logger.info(f"Got Connect Challenge: {self.challenge}")
                        
                        # Step 2: Send Connect
                        self.perform_connect()
                except Exception as e:
                    logger.error(f"Failed to parse connect challenge: {e}")

            elif header == b'B': # S2C_CONNREJECT (0x42)
                logger.warning(f"Connection Rejected: {content}")
            
            elif header == b'9': # S2C_STUFFTEXT (0x39) - usually "ping" or console commands
                # Server might ask us to run something
                pass
            
            # Note: After 'connect', the server might switch to NetChannel packets (no ffffffff)
            # OR it might send "client_connect" string in OOB? Actually, usually NetChan starts.

        else:
            # NetChannel Packet (Sequenced)
            # Since we don't have a real NetChan implementation, we can't parse compressed updates.
            # But we can try to inspect plaintext usage or keep-alives.
            
            # Very basic chatter monitoring (Best Effort)
            try:
                decoded = data.decode('latin-1', errors='ignore')
                if "sv_drop" in decoded or "Dropped" in decoded:
                    logger.warning("Possible drop message received")
                
                # Chat heuristic
                clean = "".join(c for c in decoded if c.isprintable())
                if len(clean) > 5 and ("Console" in clean or " :" in clean):
                     if self.on_chat_message:
                        asyncio.create_task(self.on_chat_message("Game", clean[:100], "game"))
            except:
                pass

            # If we are receiving NetChan packets, we are "Connected".
            if not self.is_connected:
                self.is_connected = True
                self.connection_step = 2
                logger.info("Encrypted/NetChan packet received - We are connected!")
                # Step 3: Send 'new' to finish joining
                self.send_new()
            
            # Simple Heuristic Chat Parsing
            # NetChan packets usually have an 8-byte header (Sequence + Ack) if not OOB (ffffffff)
            # data[0:4] = Sequence, data[4:8] = Ack Sequence
            
            payload = data
            if len(data) > 8 and not data.startswith(b'\xff\xff\xff\xff'):
                payload = data[8:] # Skip NetChan header
                
            try:
                # Filter for printable characters in the payload
                decoded = ''.join([chr(b) if 32 <= b <= 126 else '' for b in payload])
                # Only log if line looks meaningful (longer than 3 chars)
                if len(decoded) > 3:
                    logger.info(f"Packet payload string: {decoded}")
                    
                    # Basic Chat detection (svc_print sometimes just sends text)
                    if "SayText" in decoded or " : " in decoded:
                         # Emit to frontend
                         # We need a reference to 'sio' here, or use a callback.
                         # For now, we rely on the logger which the user sees.
                         pass
            except:
                pass

    def perform_connect(self):
        # Based on captured logs:
        # connect <proto> <challenge> "<auth_info>" "<user_info>"
        
        # 1. Auth Info
        # Using the CDKey captured from a successful connection to rule out auth issues
        # User's CDKey: c8fe91a668eb0265b3bc52cf12dccf31
        valid_cdkey = "c8fe91a668eb0265b3bc52cf12dccf31"
        
        auth_info = (
            f"\\prot\\3"
            f"\\unique\\-1"
            f"\\raw\\steam"
            f"\\cdkey\\{valid_cdkey}"
        )

        # 2. User Info
        # Added missing fields observed in valid client logs: cl_dlmax, _vgui_menus, _ah, _cl_autowepswitch
        # and increased rate/updaterate to match
        user_info = (
            f"\\name\\{self.nickname}"
            f"\\model\\gordon"
            f"\\topcolor\\30\\bottomcolor\\6"
            f"\\rate\\100000"
            f"\\cl_updaterate\\102"
            f"\\cl_lw\\1\\cl_lc\\1"
            f"\\cl_dlmax\\512"
            f"\\_vgui_menus\\1"
            f"\\_ah\\1"
            f"\\_cl_autowepswitch\\1"
            f"\\can_voice_record\\1"
        )
        
        cmd = f'connect {PROTO_VERSION} {self.challenge} "{auth_info}" "{user_info}"'
        packet = b'\xff\xff\xff\xff' + cmd.encode('ascii')
        logger.info(f"Sending connect: {cmd}")
        self.send_packet(packet)

    def send_new(self):
        # The 'new' command tells the server we are ready to enter the game world.
        # Sent as: \xff\xff\xff\xffnew
        logger.info("Sending 'new' command...")
        self.send_packet(b'\xff\xff\xff\xffnew')
        
        # Join Terrorist team (1) to enable voice/chat
        self.loop.call_later(1.0, self.send_packet, b'\xff\xff\xff\xffjointeam 1')
        self.loop.call_later(1.5, self.send_packet, b'\xff\xff\xff\xffjoinclass 1') # Select Phoenix
        self.loop.call_later(2.0, self.send_packet, b'\xff\xff\xff\xff+left')
        logger.info("Scheduled 'jointeam 1' (Terrorist) + Spin")

    async def keep_alive(self):
        logger.info("Starting KeepAlive task")
        while True:
            try:
                # Basic KeepAlive
                if self.is_connected:
                     # Send 'time' to query server time (OOB keepalive)
                     self.send_packet(b'\xff\xff\xff\xfftime')
                     
                     # Try to send 'cmd' to keep "active" status? 
                     # \xff\xff\xff\xffcmd +left might not work OOB, but worth a try
                     # self.send_packet(b'\xff\xff\xff\xffcmd sum 0')
                
                await asyncio.sleep(5) 
            except asyncio.CancelledError:
                break

    def close(self):
        self.is_connected = False
        if self.read_task: self.read_task.cancel()
        if self.keep_alive_task: self.keep_alive_task.cancel()
        try:
            self.sock.close()
        except:
            pass
