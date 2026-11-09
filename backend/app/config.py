import os


class Settings:
    OCR_WORKER_CONCURRENCY: int = int(os.getenv("OCR_WORKER_CONCURRENCY", "3"))
    OCR_JOB_TIMEOUT_SECONDS: int = int(os.getenv("OCR_JOB_TIMEOUT_SECONDS", "180"))
    DEMO_MODE: bool = os.getenv("DEMO_MODE", "false").lower() == "true"
    DEMO_USER_EMAIL: str = "demo@rachownik.app"
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")


settings = Settings()
