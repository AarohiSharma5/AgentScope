"""Prepare the database for a DEMO_MODE deployment, then exit.

Intended to run in the *background* from the start command so the web server can
bind and pass the platform health check immediately (see ``start.sh``):

    python demo_boot.py &
    exec gunicorn ... run:app

There are two independent datasets, seeded separately so the common cold-start
path stays cheap:

* **Breadth** (``seed_demo.seed``) — fills every navbar tab. This is the slow
  part over a networked database, so we only run it when the DB has no traces
  yet (or when ``DEMO_RESET_ON_BOOT`` forces a rebuild). A warm DB skips it.
* **Depth** (``scripts.seed_demo.seed``) — 90 days of analytics history with
  planted regressions + the change annotations/budgets that power the Analytics
  Insights & "Investigate" flow. It's only ~100 commits (fast), and we run it
  whenever those annotations are missing, so an existing breadth-only DB can be
  topped up without an expensive full reseed.

Behaviour is controlled by ``DEMO_RESET_ON_BOOT``:
* ``true``  → wipe and rebuild both datasets from scratch.
* otherwise → seed only what's missing (idempotent top-up), booting fast.

Safe to run when ``DEMO_MODE`` is off: it does nothing. Never raises fatally —
a seeding hiccup must not stop the web server from coming up.
"""
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("agentscope.demo_boot")


def main() -> None:
    from app import create_app
    from app.extensions import db
    from app.models.annotation import Annotation
    from app.models.trace import Trace

    app = create_app()
    if not app.config.get("DEMO_MODE"):
        logger.info("DEMO_MODE is off; skipping demo seed.")
        return

    reset = bool(app.config.get("DEMO_RESET_ON_BOOT"))
    with app.app_context():
        has_traces = db.session.query(Trace.id).first() is not None
        has_annotations = db.session.query(Annotation.id).first() is not None

    # 1) Breadth — the slow one. Skip it on a warm DB so restarts are fast.
    if reset or not has_traces:
        from seed_demo import seed

        logger.info("Seeding platform demo dataset (reset=%s)…", reset)
        seed(reset=reset)
    else:
        logger.info("Platform data present; skipping breadth seed.")

    # 2) Depth — analytics history with planted regressions + annotations/budgets
    #    that power Insights and the "Investigate" flow. Cheap, so we top it up
    #    whenever the annotations are missing (even on an otherwise-populated DB).
    #    Best-effort: a failure here must not stop the server from coming up.
    if reset or not has_annotations:
        try:
            from scripts.seed_demo import seed as seed_analytics

            analytics_app = create_app()
            with analytics_app.app_context():
                # ``reset`` here would wipe traces too; the breadth step already
                # handled any requested reset, so always append.
                seed_analytics(days=90, reset=False)
            logger.info("Analytics history (regressions + annotations + budgets) seeded.")
        except Exception:  # noqa: BLE001
            logger.exception("analytics history seed failed; continuing without it")
    else:
        logger.info("Analytics data present; skipping analytics seed.")

    logger.info("Demo dataset ready.")


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001 - never block the web server from starting
        logger.exception("demo_boot failed; starting server without (re)seeding")
