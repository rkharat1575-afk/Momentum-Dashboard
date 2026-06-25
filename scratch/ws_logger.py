import asyncio
import websockets
import json

async def listen():
    uri = "ws://localhost:8080"
    print(f"Connecting to {uri}...")
    try:
        async with websockets.connect(uri) as websocket:
            print("Connected! Listening for 65 seconds...")
            end_time = asyncio.get_event_loop().time() + 65.0
            
            with open("ws_log.txt", "w") as f:
                while asyncio.get_event_loop().time() < end_time:
                    try:
                        message = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                        data = json.loads(message)
                        msg_type = data.get("type", "unknown")
                        
                        if msg_type in ["chain_context", "score_update"]:
                            print(f"Received {msg_type}: {message[:150]}...")
                            f.write(message + "\n")
                        else:
                            # Just log type for other messages to avoid flooding
                            pass
                    except asyncio.TimeoutError:
                        pass
    except Exception as e:
        print(f"Connection failed: {e}")

asyncio.run(listen())
