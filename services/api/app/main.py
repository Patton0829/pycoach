from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.graphs import router as graphs_router
from app.api.messages import router as messages_router
from app.api.sessions import router as sessions_router
from app.api.websockets import router as websockets_router

app = FastAPI(title="PyCoach Lab API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(sessions_router)
app.include_router(messages_router)
app.include_router(graphs_router)
app.include_router(websockets_router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "pycoach-api"}
