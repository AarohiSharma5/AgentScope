"""Entry point for running the AgentScope backend."""
import os

from app import create_app

app = create_app()

if __name__ == "__main__":
    # Default to 5001 because macOS Control Center / AirPlay Receiver occupies 5000.
    port = int(os.getenv("PORT", "5001"))
    app.run(host="0.0.0.0", port=port, debug=True)
