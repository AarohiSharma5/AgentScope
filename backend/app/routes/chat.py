"""Chat endpoint that runs the fully traced chatbot flow.

The route stays thin: it validates input and delegates the entire
request-to-response lifecycle (and all tracing) to ``chat_service``.
"""
from flask import Blueprint, jsonify, request

from ..services import chat_service

chat_bp = Blueprint("chat", __name__)


@chat_bp.post("/chat")
def chat():
    """Handle a chat request and return the response with its trace ids."""
    payload = request.get_json(silent=True) or {}
    user_prompt = payload.get("user_prompt")
    if not user_prompt or not str(user_prompt).strip():
        return jsonify({"error": "user_prompt is required"}), 400

    result = chat_service.run_chat(payload)
    return jsonify(result), 201
