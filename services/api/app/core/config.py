from dataclasses import dataclass
import os
from pathlib import Path


def load_local_env() -> None:
    search_roots = [Path.cwd(), *Path(__file__).resolve().parents]
    for root in search_roots:
        env_path = root / ".env"
        if not env_path.is_file():
            continue
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line.removeprefix("export ").strip()
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("'\"")
            if key:
                os.environ.setdefault(key, value)
        return


load_local_env()


def default_curriculum_dir() -> str:
    relative_path = Path("curriculum") / "python_iterator_v1"
    for parent in Path(__file__).resolve().parents:
        candidate = parent / relative_path
        if candidate.is_dir():
            return str(candidate)
    return str(Path.cwd() / relative_path)


@dataclass(frozen=True)
class Settings:
    app_env: str = os.getenv("APP_ENV", "development")
    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://pycoach:pycoach@localhost:5432/pycoach",
    )
    llm_provider: str = os.getenv("LLM_PROVIDER", "mock")
    llm_base_url: str = os.getenv("LLM_BASE_URL", "")
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_model: str = os.getenv("LLM_MODEL", "")
    llm_timeout_seconds: float = float(os.getenv("LLM_TIMEOUT_SECONDS", "75"))
    llm_extra_body: str = os.getenv("LLM_EXTRA_BODY", "")
    curriculum_dir: str = os.getenv("CURRICULUM_DIR", default_curriculum_dir())


settings = Settings()
