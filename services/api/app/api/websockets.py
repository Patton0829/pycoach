from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.schemas.message import ConnectionReadyEvent
from app.services.websocket_manager import session_websocket_manager

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/sessions/{session_id}")
async def session_socket(websocket: WebSocket, session_id: UUID) -> None:
    session_key = str(session_id)
    await session_websocket_manager.connect(session_key, websocket)
    await session_websocket_manager.send(
        websocket,
        ConnectionReadyEvent(session_id=session_id),
    )
    try:
        while True:
            message = await websocket.receive_json()
            if message.get("type") == "ping":
                await websocket.send_json({"type": "pong", "session_id": session_key})
    except WebSocketDisconnect:
        session_websocket_manager.disconnect(session_key, websocket)
