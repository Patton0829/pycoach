from collections import defaultdict
from typing import DefaultDict, Set

from fastapi import WebSocket
from pydantic import BaseModel


class SessionWebSocketManager:
    def __init__(self) -> None:
        self._connections: DefaultDict[str, Set[WebSocket]] = defaultdict(set)

    async def connect(self, session_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections[session_id].add(websocket)

    def disconnect(self, session_id: str, websocket: WebSocket) -> None:
        connections = self._connections.get(session_id)
        if not connections:
            return
        connections.discard(websocket)
        if not connections:
            self._connections.pop(session_id, None)

    async def send(self, websocket: WebSocket, event: BaseModel) -> None:
        await websocket.send_json(event.model_dump(mode="json"))

    async def broadcast(self, session_id: str, event: BaseModel) -> None:
        disconnected = []
        for websocket in self._connections.get(session_id, set()).copy():
            try:
                await self.send(websocket, event)
            except RuntimeError:
                disconnected.append(websocket)
        for websocket in disconnected:
            self.disconnect(session_id, websocket)

session_websocket_manager = SessionWebSocketManager()
