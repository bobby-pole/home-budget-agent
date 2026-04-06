import json
import sys
import os

# Add the parent directory to sys.path to import app modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.main import app

def export_openapi():
    openapi_schema = app.openapi()
    
    # Ensure the output directory exists (root of the project)
    output_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    
    output_path = os.path.join(output_dir, "openapi.json")
    
    with open(output_path, "w") as f:
        json.dump(openapi_schema, f, indent=2)
    
    print(f"✅ OpenAPI schema exported to {output_path}")

if __name__ == "__main__":
    export_openapi()
