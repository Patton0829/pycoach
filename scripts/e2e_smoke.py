"""Real REST + WebSocket smoke test for a running PyCoach stack."""

import asyncio
import json
import os
from typing import Any

import httpx
from websockets.asyncio.client import connect

API_BASE_URL = os.getenv("PYCOACH_API_URL", "http://localhost:8000").rstrip("/")
WS_BASE_URL = os.getenv("PYCOACH_WS_URL", "ws://localhost:8000").rstrip("/")
STARTUP_TIMEOUT_SECONDS = float(os.getenv("PYCOACH_STARTUP_TIMEOUT", "60"))
EVENT_TIMEOUT_SECONDS = float(os.getenv("PYCOACH_EVENT_TIMEOUT", "90"))

FORBIDDEN_KEYS = {
    "critic_content",
    "grading_rubric",
    "reference_answer",
    "expected_reasoning",
    "provisional_knowledge_updates",
    "provisional_error_updates",
    "mastery",
    "severity",
}


def assert_student_safe(payload: Any) -> None:
    serialized = json.dumps(payload, ensure_ascii=False)
    for key in FORBIDDEN_KEYS:
        if key in serialized:
            raise AssertionError(f"Student-visible payload leaked internal key: {key}")


async def receive_until(websocket, expected_type: str, limit: int = 500) -> dict:
    for _ in range(limit):
        event = json.loads(
            await asyncio.wait_for(websocket.recv(), timeout=EVENT_TIMEOUT_SECONDS)
        )
        assert_student_safe(event)
        if event.get("type") == expected_type:
            return event
    raise AssertionError(f"Did not receive WebSocket event: {expected_type}")


async def receive_critic_or_replacement(websocket) -> dict:
    critic_event = await receive_until(websocket, "critic_reply_ready")
    if critic_event["payload"].get("session_state") == "QUESTION_INVALID":
        await receive_until(websocket, "question_invalid")
        await receive_until(websocket, "question_ready")
    return critic_event


async def post_message(
    client: httpx.AsyncClient,
    session_id: str,
    content: str,
) -> None:
    response = await client.post(
        f"/api/sessions/{session_id}/messages",
        json={"content": content},
    )
    if response.status_code != 202:
        raise AssertionError(
            f"Expected 202 for student message, got {response.status_code}: "
            f"{response.text}"
        )
    assert_student_safe(response.json())


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
        timeout=20,
        trust_env=False,
    ) as client:
        await wait_for_health(client)

        created = await client.post(
            "/api/sessions",
            json={"learner_id": "demo_user", "module": "python_iterator"},
        )
        created.raise_for_status()
        session = created.json()
        assert_student_safe(session)
        if session["state"] != "QUESTION_ACTIVE":
            raise AssertionError(f"Unexpected initial state: {session['state']}")
        session_id = session["session_id"]

        async with connect(
            f"{WS_BASE_URL}/ws/sessions/{session_id}",
            proxy=None,
        ) as websocket:
            connection = json.loads(await websocket.recv())
            if connection.get("type") != "connection_ready":
                raise AssertionError(f"Unexpected first WebSocket event: {connection}")

            await post_message(client, session_id, "iter(iterator)")
            first_critic = await receive_critic_or_replacement(websocket)

            if first_critic["payload"].get("session_state") != "QUESTION_INVALID":
                await post_message(client, session_id, "为什么不能用 iter？")
                await receive_critic_or_replacement(websocket)
            else:
                await post_message(client, session_id, "我不确定")
                await receive_critic_or_replacement(websocket)

            await post_message(client, session_id, "下一题")
            next_critic = await receive_critic_or_replacement(websocket)
            if next_critic["payload"].get("session_state") == "QUESTION_INVALID":
                await post_message(client, session_id, "我不确定")
                await receive_critic_or_replacement(websocket)
                await post_message(client, session_id, "下一题")
                await receive_critic_or_replacement(websocket)
            await receive_until(websocket, "question_ready")
            summary = await receive_until(websocket, "session_summary_ready")

        recovered = await client.get(f"/api/sessions/{session_id}")
        recovered.raise_for_status()
        final_session = recovered.json()
        assert_student_safe(final_session)
        if final_session["state"] != "QUESTION_ACTIVE":
            raise AssertionError(f"Unexpected final state: {final_session['state']}")
        if summary["payload"]["completed_question_count"] < 1:
            raise AssertionError("No completed round was recorded")

    print(
        "Smoke test passed:",
        "create → wrong answer → follow-up → next question → graph commit",
    )


if __name__ == "__main__":
    asyncio.run(main())
