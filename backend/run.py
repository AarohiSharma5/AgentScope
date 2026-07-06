"""Entry point for running the AgentScope backend."""
import os

from app import create_app

app = create_app()

if __name__ == "__main__":
    # Default to 8000 (5000 is occupied by macOS Control Center / AirPlay Receiver).
    port = int(os.getenv("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, debug=True)
