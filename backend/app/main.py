# backend/app/main.py
import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

app = FastAPI(title="Smart Budget AI")

# Tutaj będą Twoje endpointy API
@app.get("/api/health")
async def health_check():
    return {"status": "ok", "message": "Backend is running!"}

# --- KONFIGURACJA SPA (Single Page Application) ---
# Upewniamy się, że folder static istnieje (w kontenerze Dockerowym będzie tam skopiowany React)
# Lokalnie musisz uważać, bo folderu static może nie być, dopóki nie zbudujesz frontu.
if os.path.exists("static"):
    # Serwowanie plików statycznych (JS, CSS, obrazy)
    app.mount("/assets", StaticFiles(directory="static/assets"), name="assets")
    
    # Catch-all route dla React Routera
    # Każde zapytanie, które nie jest API i nie jest plikiem statycznym, zwraca index.html
    @app.get("/{full_path:path}")
    async def serve_react_app(full_path: str):
        # Sprawdź czy plik istnieje w static (np. favicon.ico)
        file_path = f"static/{full_path}"
        if os.path.exists(file_path) and os.path.isfile(file_path):
             return FileResponse(file_path)
        
        # W przeciwnym razie zwróć index.html (React obsłuży routing po stronie klienta)
        return FileResponse("static/index.html")
else:
    print("⚠️  WARNING: Folder 'static' not found. Frontend will not be served.")
    print("   (This is expected during local backend development if you haven't built the frontend)")