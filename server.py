#!/usr/bin/env python3
import asyncio
import websockets
import json
import uuid
from datetime import datetime
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class MessengerServer:
    def __init__(self):
        self.clients = {}
        self.messages = []
        self.typing_users = set()
        
    async def register_client(self, websocket):
        """Register a new client connection"""
        client_id = str(uuid.uuid4())
        username = f"User_{client_id[:6]}"
        
        client_info = {
            'id': client_id,
            'username': username,
            'websocket': websocket,
            'joined_at': datetime.now()
        }
        
        self.clients[websocket] = client_info
        logger.info(f"Client {username} connected")
        
        # Send welcome message
        welcome_data = {
            'type': 'welcome',
            'clientId': client_id,
            'username': username,
            'messages': self.messages
        }
        await websocket.send(json.dumps(welcome_data))
        
        # Notify others about new user
        join_message = {
            'id': str(uuid.uuid4()),
            'type': 'user_joined',
            'username': username,
            'timestamp': datetime.now().isoformat()
        }
        await self.broadcast_message(join_message, exclude=websocket)
        
        try:
            # Handle messages from this client
            async for message in websocket:
                await self.handle_message(websocket, message)
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            await self.unregister_client(websocket)
    
    async def unregister_client(self, websocket):
        """Unregister a client connection"""
        if websocket in self.clients:
            client_info = self.clients[websocket]
            username = client_info['username']
            
            logger.info(f"Client {username} disconnected")
            
            # Remove from typing users
            self.typing_users.discard(username)
            
            # Notify others about user leaving
            leave_message = {
                'id': str(uuid.uuid4()),
                'type': 'user_left',
                'username': username,
                'timestamp': datetime.now().isoformat()
            }
            await self.broadcast_message(leave_message, exclude=websocket)
            
            # Update typing indicator
            await self.broadcast_typing_update(exclude=websocket)
            
            # Remove client
            del self.clients[websocket]
    
    async def handle_message(self, websocket, message):
        """Handle incoming message from client"""
        try:
            data = json.loads(message)
            client_info = self.clients.get(websocket)
            
            if not client_info:
                return
            
            message_type = data.get('type')
            
            if message_type == 'message':
                await self.handle_chat_message(websocket, data)
            elif message_type == 'typing_start':
                await self.handle_typing_start(websocket, data)
            elif message_type == 'typing_stop':
                await self.handle_typing_stop(websocket, data)
            elif message_type == 'username_change':
                await self.handle_username_change(websocket, data)
                
        except json.JSONDecodeError:
            logger.error("Invalid JSON received")
        except Exception as e:
            logger.error(f"Error handling message: {e}")
    
    async def handle_chat_message(self, websocket, data):
        """Handle chat message"""
        client_info = self.clients[websocket]
        text = data.get('text', '').strip()
        
        if not text:
            return
        
        # Update username if provided
        new_username = data.get('username', '').strip()
        if new_username and new_username != client_info['username']:
            old_username = client_info['username']
            client_info['username'] = new_username
            
            # Notify about username change
            username_change_msg = {
                'id': str(uuid.uuid4()),
                'type': 'username_changed',
                'oldUsername': old_username,
                'newUsername': new_username,
                'timestamp': datetime.now().isoformat()
            }
            await self.broadcast_message(username_change_msg)
        
        # Create message
        message_data = {
            'id': str(uuid.uuid4()),
            'type': 'message',
            'username': client_info['username'],
            'text': text,
            'timestamp': datetime.now().isoformat()
        }
        
        # Store message (keep only last 100)
        self.messages.append(message_data)
        if len(self.messages) > 100:
            self.messages.pop(0)
        
        # Broadcast to all clients
        await self.broadcast_message(message_data)
    
    async def handle_typing_start(self, websocket, data):
        """Handle typing start"""
        client_info = self.clients[websocket]
        username = data.get('username', client_info['username'])
        
        # Update username if provided
        if username != client_info['username']:
            client_info['username'] = username
        
        self.typing_users.add(username)
        await self.broadcast_typing_update(exclude=websocket)
    
    async def handle_typing_stop(self, websocket, data):
        """Handle typing stop"""
        client_info = self.clients[websocket]
        username = client_info['username']
        
        self.typing_users.discard(username)
        await self.broadcast_typing_update(exclude=websocket)
    
    async def handle_username_change(self, websocket, data):
        """Handle username change"""
        client_info = self.clients[websocket]
        new_username = data.get('username', '').strip()
        
        if not new_username or new_username == client_info['username']:
            return
        
        old_username = client_info['username']
        client_info['username'] = new_username
        
        # Update typing users set
        if old_username in self.typing_users:
            self.typing_users.discard(old_username)
            self.typing_users.add(new_username)
        
        # Notify all clients
        username_change_msg = {
            'id': str(uuid.uuid4()),
            'type': 'username_changed',
            'oldUsername': old_username,
            'newUsername': new_username,
            'timestamp': datetime.now().isoformat()
        }
        await self.broadcast_message(username_change_msg)
        
        # Send confirmation to the client
        confirmation = {
            'type': 'username_updated',
            'username': new_username
        }
        await websocket.send(json.dumps(confirmation))
    
    async def broadcast_message(self, message_data, exclude=None):
        """Broadcast message to all connected clients"""
        if not self.clients:
            return
        
        message_json = json.dumps(message_data)
        disconnected_clients = []
        
        for websocket, client_info in self.clients.items():
            if websocket == exclude:
                continue
            
            try:
                await websocket.send(message_json)
            except websockets.exceptions.ConnectionClosed:
                disconnected_clients.append(websocket)
            except Exception as e:
                logger.error(f"Error sending message to client: {e}")
                disconnected_clients.append(websocket)
        
        # Clean up disconnected clients
        for websocket in disconnected_clients:
            await self.unregister_client(websocket)
    
    async def broadcast_typing_update(self, exclude=None):
        """Broadcast typing indicator update"""
        typing_data = {
            'type': 'typing_update',
            'typingUsers': list(self.typing_users)
        }
        await self.broadcast_message(typing_data, exclude=exclude)

async def main():
    """Main server function"""
    server = MessengerServer()
    
    logger.info("Starting WebSocket server on localhost:8080")
    
    # Start the WebSocket server
    async with websockets.serve(
        server.register_client,
        "localhost",
        8080,
        ping_interval=20,
        ping_timeout=10
    ):
        logger.info("WebSocket server is running on ws://localhost:8080")
        # Keep the server running
        await asyncio.Future()  # Run forever

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Server error: {e}")
