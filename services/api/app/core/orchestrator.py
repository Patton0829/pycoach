from functools import lru_cache

from app.core.dependencies import get_llm_provider
from app.services.session_orchestrator import LearningSessionOrchestrator
from app.services.websocket_manager import session_websocket_manager


@lru_cache
def get_session_orchestrator() -> LearningSessionOrchestrator:
    return LearningSessionOrchestrator(
        provider=get_llm_provider(),
        websocket_manager=session_websocket_manager,
    )
