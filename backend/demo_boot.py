"""Prepare the database for a DEMO_MODE deployment.

Runs in two explicit phases (see ``start.sh``) so that schema creation is
*never* concurrent — a concurrent ``CREATE TABLE`` from two processes against the
same database races and one of them dies with a DDL error ("Worker failed to
boot"). The phases:

    python demo_boot.py schema   # sync, single-threaded: (drop if reset +) create_all
    python demo_boot.py seed &   # background: insert data only, never issues DDL

``start.sh`` runs ``schema`` to completion first, then launches ``seed`` in the
background and execs gunicorn. Because the schema already exists by then, both
the gunicorn worker's own ``create_all()`` and the seeder are no-ops at the DDL
level — nothing races.

Datasets seeded (only what's missing, unless DEMO_RESET_ON_BOOT forces a wipe in
the schema phase):
* **Breadth** (``seed_demo.seed``) — fills every navbar tab. Slow over a remote
  DB, so it only runs when there are no traces yet.
* **Depth** (``scripts.seed_demo.seed``) — 90 days of analytics history with
  planted regressions + change annotations/budgets that power the Analytics
  Insights & "Investigate" flow. Cheap (~100 commits); runs whenever the
  annotations are missing.

Safe to run when ``DEMO_MODE`` is off: it does nothing. Never raises fatally.
"""
import logging
import os
import sys

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("agentscope.demo_boot")


def _prepare_schema() -> None:
    """Create (and optionally reset) the schema. Single-threaded, synchronous."""
    from app import create_app
    from app.extensions import db

    app = create_app()
    if not app.config.get("DEMO_MODE"):
        logger.info("DEMO_MODE is off; skipping schema prep.")
        return

    reset = bool(app.config.get("DEMO_RESET_ON_BOOT"))
    with app.app_context():
        if reset:
            logger.info("DEMO_RESET_ON_BOOT=true → dropping existing schema…")
            db.drop_all()
        db.create_all()
    logger.info("Schema ready (reset=%s).", reset)


def _seed() -> None:
    """Insert demo data. Runs in the background; must never issue DDL."""
    # Guarantee this process never runs create_all() — the schema phase owns the
    # schema, so we opt into "migrations own the schema" purely to suppress DDL.
    os.environ.setdefault("USE_MIGRATIONS", "true")

    from app import create_app
    from app.extensions import db
    from app.models.annotation import Annotation
    from app.models.trace import Trace

    app = create_app()
    if not app.config.get("DEMO_MODE"):
        logger.info("DEMO_MODE is off; skipping demo seed.")
        return

    with app.app_context():
        has_traces = db.session.query(Trace.id).first() is not None
        has_annotations = db.session.query(Annotation.id).first() is not None

    # 1) Breadth — the slow one. Skip it on a warm DB so restarts stay fast.
    if not has_traces:
        from seed_demo import seed

        logger.info("Seeding platform demo dataset…")
        seed(reset=False)  # schema already handled any requested reset
    else:
        logger.info("Platform data present; skipping breadth seed.")

    # 2) Depth — analytics history with planted regressions + annotations/budgets
    #    that power Insights and the "Investigate" flow. Cheap, so top it up
    #    whenever the annotations are missing. Best-effort.
    if not has_annotations:
        try:
            from scripts.seed_demo import seed as seed_analytics

            analytics_app = create_app()
            with analytics_app.app_context():
                seed_analytics(days=90, reset=False)
            logger.info("Analytics history (regressions + annotations + budgets) seeded.")
        except Exception:  # noqa: BLE001
            logger.exception("analytics history seed failed; continuing without it")
    else:
        logger.info("Analytics data present; skipping analytics seed.")

    logger.info("Demo dataset ready.")


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    if mode == "schema":
        _prepare_schema()
    elif mode == "seed":
        _seed()
    else:  # "all" — convenience for local runs (sequential, so no race)
        _prepare_schema()
        _seed()


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001 - never block the web server from starting
        logger.exception("demo_boot failed; starting server without (re)seeding")
