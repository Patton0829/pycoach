"""Verify Questioner is complete and Critic uses WebSocket streaming."""

import asyncio
import json
import os
from collections import Counter

import httpx
from websockets.asyncio.client import connect

API_BASE_URL = os.getenv("PYCOACH_API_URL", "http://localhost:8000").rstrip("/")
WS_BASE_URL = os.getenv("PYCOACH_WS_URL", "ws://localhost:8000").rstrip("/")
STARTUP_TIMEOUT_SECONDS = float(os.getenv("PYCOACH_STARTUP_TIMEOUT", "60"))
REQUEST_TIMEOUT_SECONDS = float(os.getenv("PYCOACH_REQUEST_TIMEOUT", "60"))


async def receive_phase(websocket, final_type: str) -> Counter:
    counts: Counter = Counter()
    for _ in range(500):
        event = json.loads(await asyncio.wait_for(websocket.recv(), timeout=90))
        event_type = event.get("type")
        counts[event_type] += 1
        if event_type == final_type:
            return counts
    raise AssertionError(f"Did not receive final event: {final_type}")


async def wait_for_health(client: httpx.AsyncClient) -> None:
    deadline = asyncio.get_running_loop().time() + STARTUP_TIMEOUT_SECONDS
    last_error: Exception | None = None

    while asyncio.get_running_loop().time() < deadline:
        try:
            response = await client.get("/health")
            response.raise_for_status()
            return
        except (httpx.HTTPError, httpx.InvalidURL) as exc:
            last_error = exc
            await asyncio.sleep(1)

    raise RuntimeError(
        f"API did not become healthy within {STARTUP_TIMEOUT_SECONDS:g}s: "
        f"{last_error}"
    )


async def main() -> None:
    async with httpx.AsyncClient(
        base_url=API_BASE_URL,
        timeout=REQUEST_TIMEOUT_SECONDS,
        trust_env=False,
    ) as client:
        await wait_for_health(client)

        created = await client.post(
            "/api/sessions",
            json={"learner_id": "demo_user", "module": "python_iterator"},
        )
        created.raise_for_status()
        session = created.json()
        if session["state"] != "QUESTION_ACTIVE":
            raise AssertionError(f"Unexpected initial state: {session['state']}")
        if not session["messages"] or session["messages"][0]["role"] != "questioner":
            raise AssertionError("Questioner did not return a complete initial question")
        session_id = session["session_id"]

        async with connect(
            f"{WS_BASE_URL}/ws/sessions/{session_id}",
            proxy=None,
        ) as websocket:
            connection = json.loads(await websocket.recv())
            if connection.get("type") != "connection_ready":
                raise AssertionError(f"Unexpected first event: {connection}")

            accepted = await client.post(
                f"/api/sessions/{session_id}/messages",
                json={"content": "我不确定"},
            )
            if accepted.status_code != 202:
                raise AssertionError(
                    f"Expected 202, got {accepted.status_code}: {accepted.text}"
                )

            critic_counts = await receive_phase(websocket, "critic_reply_ready")
            if critic_counts["message_stream_delta"] < 2:
                raise AssertionError(
                    f"Critic did not stream multiple deltas: {critic_counts}"
                )

    print(
        "Streaming smoke passed:",
        "Questioner=complete,",
        f"Critic deltas={critic_counts['message_stream_delta']}",
    )


if __name__ == "__main__":
    asyncio.run(main())
