#!/usr/bin/env python3
"""
Simple script to test WebSocket authentication for game scores
"""
import asyncio
import websockets
import json

async def test_game_websocket():
    """Test WebSocket connection to game scoring"""
    uri = "ws://localhost:8000/ws/games/1869/"  # Replace with actual game ID
    
    try:
        print(f"🔌 Connecting to {uri}...")
        async with websockets.connect(uri) as websocket:
            print("✅ Connected successfully!")
            
            # Wait for any messages
            try:
                message = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                print(f"📨 Received: {message}")
            except asyncio.TimeoutError:
                print("⏰ No messages received (timeout)")
                
    except websockets.exceptions.ConnectionClosedError as e:
        print(f"❌ Connection closed: {e}")
    except Exception as e:
        print(f"💥 Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_game_websocket())
