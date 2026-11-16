import os
import sys
from typing import Optional


class Settings:
    OCR_WORKER_CONCURRENCY: int = int(os.getenv("OCR_WORKER_CONCURRENCY", "3"))
    OCR_JOB_TIMEOUT_SECONDS: int = int(os.getenv("OCR_JOB_TIMEOUT_SECONDS", "180"))
    DEMO_MODE: bool = os.getenv("DEMO_MODE", "false").lower() == "true"
    DEMO_USER_EMAIL: str = "demo@rachownik.app"
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")

    # Durable import scheduler / worker settings (#257, #264)
    _default_role: str = (
        "central_vps"
        if (DEMO_MODE or ENVIRONMENT.strip().lower() == "production")
        else "trusted_local"
    )
    IMPORT_WORKER_ROLE: str = os.getenv("IMPORT_WORKER_ROLE", _default_role)
    _initial_import_worker_role: str = IMPORT_WORKER_ROLE
    IMPORT_WORKER_ENABLED: Optional[bool] = (
        val.lower() == "true"
        if (val := os.getenv("IMPORT_WORKER_ENABLED")) is not None
        else None
    )

    def resolve_import_worker_role(self) -> str:
        """Resolve worker role fail-closed for production/demo unless explicitly trusted."""
        if self.IMPORT_WORKER_ROLE != self._initial_import_worker_role:
            return self.IMPORT_WORKER_ROLE.strip().lower()
        if (env_role := os.getenv("IMPORT_WORKER_ROLE")) is not None:
            return env_role.strip().lower()
        if self.DEMO_MODE or os.getenv("DEMO_MODE", "false").lower() == "true":
            return "central_vps"
        env_name = (os.getenv("ENVIRONMENT") or self.ENVIRONMENT).strip().lower()
        if env_name == "production":
            return "central_vps"
        return self.IMPORT_WORKER_ROLE.strip().lower()

    def is_import_worker_enabled(self) -> bool:
        """Evaluate worker activation dynamically so pytest collection never freezes True."""
        if self.IMPORT_WORKER_ENABLED is not None:
            return self.IMPORT_WORKER_ENABLED
        raw = os.getenv("IMPORT_WORKER_ENABLED")
        if raw is not None:
            return raw.lower() == "true"
        if os.getenv("PYTEST_CURRENT_TEST") or "pytest" in sys.modules:
            return False
        return True
    IMPORT_WORKER_POLL_INTERVAL_SECONDS: float = float(
        os.getenv("IMPORT_WORKER_POLL_INTERVAL_SECONDS", "5.0")
    )
    IMPORT_WORKER_LEASE_SECONDS: int = int(os.getenv("IMPORT_WORKER_LEASE_SECONDS", "120"))
    IMPORT_WORKER_MAX_ATTEMPTS: int = int(os.getenv("IMPORT_WORKER_MAX_ATTEMPTS", "5"))
    IMPORT_WORKER_BASE_BACKOFF_SECONDS: int = int(
        os.getenv("IMPORT_WORKER_BASE_BACKOFF_SECONDS", "30")
    )
    IMPORT_WORKER_MAX_BACKOFF_SECONDS: int = int(
        os.getenv("IMPORT_WORKER_MAX_BACKOFF_SECONDS", "3600")
    )
    IMPORT_SYNC_INTERVAL_SECONDS: int = int(
        os.getenv("IMPORT_SYNC_INTERVAL_SECONDS", "21600")
    )


settings = Settings()
