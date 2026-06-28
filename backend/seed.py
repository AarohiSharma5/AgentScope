"""Seed the database with sample traces for local development/demo."""
import random
from datetime import datetime, timedelta, timezone

from app import create_app
from app.extensions import db
from app.models.trace import Trace, TraceStatus
from app.services.trace_service import estimate_cost

MODELS = ["gpt-4o", "gpt-4o-mini", "claude-3-5-sonnet", "gpt-3.5-turbo"]

SAMPLE_PROMPTS = [
    "Summarize the latest quarterly earnings report.",
    "Write a Python function to deduplicate a list.",
    "Explain the difference between TCP and UDP.",
    "Draft a polite follow-up email to a client.",
    "What are the tradeoffs of microservices vs monolith?",
]

SYSTEM_PROMPT = "You are AgentScope, a helpful and concise AI assistant."


def seed(n: int = 25):
    app = create_app()
    with app.app_context():
        db.drop_all()
        db.create_all()

        for i in range(n):
            model = random.choice(MODELS)
            input_tokens = random.randint(50, 800)
            output_tokens = random.randint(20, 600)
            status = TraceStatus.SUCCESS if random.random() > 0.12 else TraceStatus.FAILED

            trace = Trace(
                user_prompt=random.choice(SAMPLE_PROMPTS),
                system_prompt=SYSTEM_PROMPT,
                model_name=model,
                timestamp=datetime.now(timezone.utc) - timedelta(minutes=random.randint(0, 5000)),
                latency_ms=round(random.uniform(180, 4200), 2),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
                estimated_cost=estimate_cost(model, input_tokens, output_tokens),
                retrieved_documents=(
                    [
                        {"title": "Knowledge Base Article", "score": 0.91},
                        {"title": "FAQ entry", "score": 0.78},
                    ]
                    if random.random() > 0.5
                    else None
                ),
                tool_calls=(
                    [{"name": "search_web", "arguments": {"query": "earnings"}}]
                    if random.random() > 0.7
                    else None
                ),
                final_response=(
                    "Here is a concise answer based on your request..."
                    if status == TraceStatus.SUCCESS
                    else None
                ),
                status=status,
                error_message=None if status == TraceStatus.SUCCESS else "RateLimitError: 429",
            )
            db.session.add(trace)

        db.session.commit()
        print(f"Seeded {n} traces.")


if __name__ == "__main__":
    seed()
