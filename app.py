import asyncio
import logging
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import socketio
import uvicorn
from goldsrc_client import GoldSrcClient
from cs16_parser import CS16ServerParser # Import the new parser

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("App")

app = FastAPI()

# Socket.IO
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')
socket_app = socketio.ASGIApp(sio, app)

# Serve Static Files (at root, with html=True to serve index.html)
app.mount("/", StaticFiles(directory="public", html=True), name="public")

# We don't need a separate index route anymore as StaticFiles(html=True) handles it.
# But if we did, we'd ensure it doesn't conflict. 
# Since we mount at root as the last step (implicitly or explicitly), it catches everything not matched.
# Note: FastAPI evaluates routes in order. We should remove the explicit @app.get("/") if we use mount at root.

# State
clients = {} # sid -> GoldSrcClient

@sio.event
async def connect(sid, environ):
    logger.info(f"Web Client connected: {sid}")

@sio.event
async def join_game(sid, data):
    # data: { nickname: str, server_ip: str }
    nickname = data.get('nickname', 'Player')
    server_ip = data.get('server_ip', '127.0.0.1:27015')
    
    if ':' in server_ip:
        host, port_str = server_ip.split(':')
        # Clean port string (remove potential invisible chars)
        port = int(''.join(filter(str.isdigit, port_str)))
    else:
        host = server_ip
        port = 27015
        
    logger.info(f"Starting GoldSrc Client for {sid} -> {host}:{port}")
    
    # Create Callback
    async def on_back_msg(user, text, type):
        await sio.emit('chat_message', {'user': user, 'text': text, 'type': type}, room=sid)

    # Use CS16ServerParser for robust player list fetching
    # We will run this in a separate async loop inside app.py instead of GoldSrcClient
    # logic: app.py handles A2S queries (stateless/UDP), GoldSrcClient handles Game Connection (Stateful)
    
    parser = CS16ServerParser(timeout=2)
    
    async def poll_players_task(target_host, target_port, target_sid):
        logger.info(f"Starting separate poller for {target_host}:{target_port}")
        while target_sid in clients:
            try:
                # Run blocking parser in thread executor
                data = await asyncio.to_thread(parser.query_server_full, target_host, target_port)
                
                # Debug logging
                if data:
                    logger.info(f"Parser Data: {data.keys()}")
                    if 'players_list' in data:
                        logger.info(f"Found {len(data['players_list'])} players in parser data")
                    else:
                         logger.warning("No 'players_list' key in data")
                else:
                    logger.warning("Parser returned None")
                
                if data:
                    # Send basic info (Name, Map)
                    if 'name' in data:
                        await sio.emit('server_info', data, room=target_sid)

                    if 'players_list' in data:
                        players = data['players_list']
                        # Normalize keys for frontend
                        frontend_players = []
                        for p in players:
                             # cs16_parser returns: name, score, time_formatted
                             frontend_players.append({
                                 "name": p.get('name', 'Unknown'), 
                                 "score": p.get('score', 0), 
                                 "time": 0 # Time is formatted string in parser, we can parse or ignore
                             })
                        
                        await sio.emit('player_list_update', frontend_players, room=target_sid)
                        # Log to frontend console
                        await sio.emit('chat_message', {'user': 'System', 'text': f"Updated {len(players)} players from {target_host}", 'type': 'console'}, room=target_sid)
            except Exception as e:
                logger.error(f"Poll task error: {e}")
            
            await asyncio.sleep(5)

    gs_client = GoldSrcClient(host, port, nickname, on_chat_message=on_back_msg)
    clients[sid] = gs_client
    
    # Start connection in background
    asyncio.create_task(gs_client.connect())
    
    # Start Poller
    asyncio.create_task(poll_players_task(host, port, sid))
    
    await sio.emit('chat_message', {'user': 'System', 'text': f'Connecting to {host}:{port}...', 'type': 'system'}, room=sid)

@sio.event
async def chat_message(sid, msg):
    # Send to Game Server
    if sid in clients:
        # await clients[sid].send_chat(msg) 
        pass
    
    # Echo back to web
    await sio.emit('chat_message', {'user': 'Me', 'text': msg, 'type': 'user'}, room=sid)

@sio.event
async def disconnect(sid):
    logger.info(f"Web Client disconnected: {sid}")
    if sid in clients:
        clients[sid].close()
        del clients[sid]

if __name__ == "__main__":
    uvicorn.run(socket_app, host="0.0.0.0", port=8000, ssl_keyfile="key.pem", ssl_certfile="cert.pem")
