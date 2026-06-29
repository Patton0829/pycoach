import unittest
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app


class SessionWebSocketTests(unittest.TestCase):
    def test_connection_ready_and_ping(self) -> None:
        session_id = uuid4()
        with TestClient(app).websocket_connect(
            f"/ws/sessions/{session_id}"
        ) as websocket:
            ready = websocket.receive_json()
            self.assertEqual(ready["type"], "connection_ready")
            self.assertEqual(ready["session_id"], str(session_id))

            websocket.send_json({"type": "ping"})
            pong = websocket.receive_json()
            self.assertEqual(pong["type"], "pong")
            self.assertEqual(pong["session_id"], str(session_id))


if __name__ == "__main__":
    unittest.main()
