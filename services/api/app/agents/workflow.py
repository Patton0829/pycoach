"""Bounded LangGraph workflows for the two existing model roles.

Only the named ``questioner`` or ``critic`` node calls a model. Validation,
repair routing and fallback nodes are deterministic application code. Each
invocation has its own state; database sessions and streaming callbacks stay
in local closures, never in graph state or a persistent checkpointer.
"""

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Generic, Literal, Optional, Type

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from app.llm.base import SchemaT


class AgentWorkflowState(TypedDict):
    attempts: int
    candidate: Any
    accepted: bool
    validation_feedback: Optional[str]
    error: Optional[str]
    result: Any
    used_fallback: bool


@dataclass(frozen=True)
class AgentWorkflowResult(Generic[SchemaT]):
    value: Optional[SchemaT]
    retry_count: int
    used_fallback: bool
    error: Optional[str]


class StructuredAgentWorkflow(Generic[SchemaT]):
    """Run model -> validation -> repair/fallback with at most two calls.

    Retryable exception types are supplied by each service to preserve its
    existing error contract. Cancellation and unexpected programming errors
    propagate rather than being converted into successful fallback results.
    """

    def __init__(
        self,
        *,
        role: Literal["questioner", "critic"],
        schema: Type[SchemaT],
        invoke: Callable[[Optional[str]], Awaitable[SchemaT]],
        retry_exceptions: tuple[Type[Exception], ...],
        validate: Optional[Callable[[SchemaT], None]] = None,
        fallback: Optional[Callable[[], SchemaT]] = None,
        on_rejected: Optional[Callable[[str, int], Awaitable[None]]] = None,
    ) -> None:
        self.role = role
        self.schema = schema
        self.invoke = invoke
        self.retry_exceptions = retry_exceptions
        self.validate = validate
        self.fallback = fallback
        self.on_rejected = on_rejected

        builder = StateGraph(AgentWorkflowState)
        builder.add_node(role, self._call_model)
        builder.add_node("validate", self._validate)
        builder.add_node("rejected", self._rejected)
        builder.add_node("repair", self._repair)
        builder.add_node("fallback", self._fallback)
        builder.add_node("complete", self._complete)
        builder.add_edge(START, role)
        builder.add_edge(role, "validate")
        builder.add_conditional_edges(
            "validate",
            lambda state: "complete" if state["accepted"] else "rejected",
            {"complete": "complete", "rejected": "rejected"},
        )
        builder.add_conditional_edges(
            "rejected",
            lambda state: "repair" if state["attempts"] < 2 else "fallback",
            {"repair": "repair", "fallback": "fallback"},
        )
        builder.add_edge("repair", role)
        builder.add_edge("fallback", END)
        builder.add_edge("complete", END)
        self.graph = builder.compile()

    @staticmethod
    def initial_state() -> AgentWorkflowState:
        return {
            "attempts": 0,
            "candidate": None,
            "accepted": False,
            "validation_feedback": None,
            "error": None,
            "result": None,
            "used_fallback": False,
        }

    async def run(self) -> AgentWorkflowResult[SchemaT]:
        state = await self.graph.ainvoke(self.initial_state())
        return AgentWorkflowResult(
            value=state["result"],
            retry_count=state["attempts"] - 1,
            used_fallback=state["used_fallback"],
            error=state["error"],
        )

    async def _call_model(self, state: AgentWorkflowState) -> dict:
        attempts = state["attempts"] + 1
        try:
            candidate = await self.invoke(state["validation_feedback"])
            return {"attempts": attempts, "candidate": candidate, "error": None}
        except self.retry_exceptions as error:
            return {"attempts": attempts, "candidate": None, "error": str(error)}

    async def _validate(self, state: AgentWorkflowState) -> dict:
        if state["error"] is not None:
            return {"accepted": False}
        try:
            candidate = self.schema.model_validate(state["candidate"])
            if self.validate is not None:
                self.validate(candidate)
            return {"candidate": candidate, "accepted": True}
        except self.retry_exceptions as error:
            return {"candidate": None, "accepted": False, "error": str(error)}

    async def _rejected(self, state: AgentWorkflowState) -> dict:
        if self.on_rejected is not None:
            await self.on_rejected(state["error"] or "Invalid model output", state["attempts"])
        return {}

    async def _repair(self, state: AgentWorkflowState) -> dict:
        return {"validation_feedback": state["error"], "accepted": False}

    async def _fallback(self, state: AgentWorkflowState) -> dict:
        result = self.fallback() if self.fallback is not None else None
        if result is not None:
            result = self.schema.model_validate(result)
        return {"result": result, "used_fallback": True}

    async def _complete(self, state: AgentWorkflowState) -> dict:
        return {"result": state["candidate"], "used_fallback": False}
