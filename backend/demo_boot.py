"""Prepare the database for a DEMO_MODE deployment, then exit.

Intended to run *once* as part of the start command, before gunicorn:

    python demo_boot.py && gunicorn ... run:app

Behaviour (controlled by env vars, read via the app config):
* ``DEMO_RESET_ON_BOOT=true`` → wipe and reseed a pristine demo dataset every
  boot. Pairs with a free host that spins down when idle, keeping the demo
  fresh for the next visitor.
* otherwise → seed only if the database is empty (first boot / new DB), so a
  warm restart keeps whatever is there and boots fast.

Safe to run when ``DEMO_MODE`` is off: it does nothing. Never raises fatally —
a seeding hiccup must not stop the web server from coming up.
"""
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("agentscope.demo_boot")


def main() -> None:
    from app import create_app
    from app.extensions import db
    from app.models.trace import Trace

    app = create_app()
    if not app.config.get("DEMO_MODE"):
        logger.info("DEMO_MODE is off; skipping demo seed.")
        return

    reset = bool(app.config.get("DEMO_RESET_ON_BOOT"))
    with app.app_context():
        has_data = db.session.query(Trace.id).first() is not None

    if not reset and has_data:
        logger.info("Demo database already populated; skipping seed.")
        return

    # ``seed`` builds its own app context and (with reset) drops/recreates the
    # schema before populating it via the real engines/SDK.
    from seed_demo import seed

    logger.info("Seeding demo dataset (reset=%s)…", reset)
    seed(reset=reset)
    logger.info("Demo dataset ready.")


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001 - never block the web server from starting
        logger.exception("demo_boot failed; starting server without (re)seeding")
