"""Chat endpoint that runs the fully traced chatbot flow.

The route stays thin: it validates input and delegates the entire
request-to-response lifecycle (and all tracing) to ``chat_service``.
"""
from flask import Blueprint, jsonify

from ..auth import rate_limited
from ..errors import error_response, get_json_body
from ..services import chat_service

chat_bp = Blueprint("chat", __name__)


@chat_bp.post("/chat")
@rate_limited(config_key="RATE_LIMIT_CHAT")
def chat():
    """Handle a chat request and return the response with its trace ids."""
    payload = get_json_body()
    user_prompt = payload.get("user_prompt")
    if not user_prompt or not str(user_prompt).strip():
        return error_response("user_prompt is required", 400)

    result = chat_service.run_chat(payload)
    return jsonify(result), 201
