"""Seed sample agent execution traces for local development/demo.

Attaches a few agent runs (with steps, tools, memory and retriever calls) to an
existing request trace, using the TraceRecorder SDK. Safe to run repeatedly;
each run appends new sample data.
"""
from app import create_app
from app.extensions import db
from app.models.trace import Trace
from app.utils.trace_recorder import TraceRecorder


def seed():
    app = create_app()
    with app.app_context():
        # Attach to the most recent request, or create one if none exist.
        request = Trace.query.order_by(Trace.id.desc()).first()
        if request is None:
            request = Trace(model_name="gpt-4o", user_prompt="Demo", status="success")
            db.session.add(request)
            db.session.commit()

        trace = TraceRecorder(request.id)

        # --- A successful planner run with a nested worker -------------------
        planner = trace.start_agent(
            name="Planner", type="planner", metadata={"objective": "Answer question"}
        )

        s1 = trace.add_step(
            planner,
            step_type="reasoning",
            name="Understand Question",
            input="What was Q3 revenue and how does it compare to Q2?",
        )
        trace.record_memory(
            s1,
            memory_type="vector",
            query="Q3 revenue",
            retrieved_text="Q3 revenue was $4.2M.",
            similarity_score=0.91,
            used=True,
            latency_ms=42.0,
        )
        trace.finish_step(s1, output="Need revenue figures for Q2 and Q3.")

        s2 = trace.add_step(planner, step_type="retrieval", name="Retrieve Financials")
        trace.record_retriever(
            s2,
            query="quarterly revenue 2026",
            retrieved_documents=[
                {"title": "Q3 Earnings", "source": "chroma", "score": 0.93},
                {"title": "Q2 Earnings", "source": "pinecone", "score": 0.87},
            ],
            embedding_time_ms=12.5,
            retrieval_time_ms=88.0,
        )
        trace.finish_step(s2, output="Found Q2 ($3.6M) and Q3 ($4.2M) figures.")

        s3 = trace.add_step(planner, step_type="action", name="Compute Growth")
        trace.record_tool(
            s3,
            tool_name="calculator",
            arguments={"expression": "(4.2 - 3.6) / 3.6 * 100"},
            result="16.67",
            latency_ms=3.1,
        )
        trace.record_tool(
            s3,
            tool_name="search",
            arguments={"query": "industry average revenue growth"},
            result='{"avg": "10%"}',
            latency_ms=210.4,
        )
        trace.finish_step(
            s3,
            output="Q3 grew 16.7% over Q2, above the ~10% industry average.",
            token_usage={"prompt": 320, "completion": 90, "total": 410},
            cost=0.0021,
        )

        worker = trace.start_agent(name="Verifier", type="worker", parent=planner)
        sv = trace.add_step(worker, step_type="verification", name="Verify Numbers")
        trace.finish_step(sv, output="Figures verified against source documents.")
        trace.finish_agent(worker)

        trace.finish_agent(planner)

        # --- A failed run (exception-safe context manager) -------------------
        try:
            with trace.agent(name="Summarizer", type="worker") as run:
                with trace.step(run, step_type="llm", name="Summarize") as st:
                    trace.record_tool(
                        st,
                        tool_name="llm_call",
                        arguments={"model": "gpt-4o"},
                        status="failed",
                        error_message="RateLimitError: 429",
                        latency_ms=1500.0,
                    )
                    raise RuntimeError("RateLimitError: 429")
        except RuntimeError:
            pass

        print(f"Seeded agent runs for request #{request.id}.")


if __name__ == "__main__":
    seed()
