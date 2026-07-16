"""Business logic and persistence for prompt versions (v0.5).

Captures versioned, content-hashed snapshots of the prompts assembled by agent
runs so they can be diffed over time. Versions are recorded automatically from
:func:`app.services.trace_service.create_prompt_assembly`; consecutive identical
prompts (same hash) are de-duplicated rather than creating a new version.
"""
import hashlib
import logging
from typing import Optional

from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models.evaluation_trace import PromptVersion
from ..utils.sorting import apply_sort, is_valid_sort
from ..utils.unit_of_work import commit as _commit
from ..utils.validation import ensure_json_object

logger = logging.getLogger("agentscope")

#: How many times to recompute ``v{n}`` and retry when a concurrent writer wins
#: the race for the same version label. Each retry re-reads the current count, so
#: a handful of attempts comfortably absorbs realistic write concurrency.
_MAX_VERSION_ATTEMPTS = 5


def prompt_hash(text: Optional[str]) -> str:
    """Return a stable SHA-256 hex digest of the prompt text."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _next_auto_version(agent_run_id: int) -> str:
    """Return the next ``v{n}`` label for a run based on its current count."""
    count = PromptVersion.query.filter_by(agent_run_id=agent_run_id).count()
    return f"v{count + 1}"


def record_prompt_version(
    agent_run_id: int,
    prompt_text: Optional[str],
    version: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> PromptVersion:
    """Persist a new prompt version for an agent run (committed), or reuse the
    latest one when the prompt is unchanged (same hash).

    ``version`` auto-increments as ``v1``, ``v2`` … per agent run when omitted.

    Auto-versioning is inherently racy (two concurrent callers can both compute
    ``v{count+1}``). A ``UNIQUE(agent_run_id, version)`` constraint makes the
    duplicate impossible at the database level; here we catch the resulting
    :class:`IntegrityError`, recompute the next label and retry so callers still
    get a fresh, gap-free version instead of a hard failure. Each attempt is
    wrapped in a SAVEPOINT so a conflict rolls back only the failed insert,
    leaving any surrounding batch transaction (see :mod:`app.utils.unit_of_work`)
    intact.
    """
    digest = prompt_hash(prompt_text)
    latest = (
        PromptVersion.query.filter_by(agent_run_id=agent_run_id)
        .order_by(PromptVersion.created_at.desc())
        .first()
    )
    if latest is not None and latest.hash == digest:
        return latest

    metadata_obj = ensure_json_object(metadata, "metadata")
    explicit_version = version is not None
    attempts = 1 if explicit_version else _MAX_VERSION_ATTEMPTS

    for attempt in range(attempts):
        resolved = version if explicit_version else _next_auto_version(agent_run_id)
        prompt_version = PromptVersion(
            agent_run_id=agent_run_id,
            version=resolved,
            prompt_text=prompt_text,
            hash=digest,
            prompt_metadata=metadata_obj,
        )
        savepoint = db.session.begin_nested()
        db.session.add(prompt_version)
        try:
            db.session.flush()
        except IntegrityError:
            savepoint.rollback()
            # An explicit version that collides is a genuine caller error; an
            # auto-computed one just lost the race, so recompute and retry.
            if explicit_version or attempt == attempts - 1:
                raise
            continue
        savepoint.commit()
        _commit()
        logger.debug(
            "Recorded prompt version id=%s run_id=%s version=%s",
            prompt_version.id, agent_run_id, resolved,
        )
        return prompt_version


def get_prompt_version(prompt_version_id: int) -> Optional[PromptVersion]:
    """Return a prompt version by id, or None."""
    return db.session.get(PromptVersion, prompt_version_id)


PROMPT_VERSION_SORTABLE = {"created_at", "version"}
_PROMPT_VERSION_SORT_COLUMNS = {
    name: getattr(PromptVersion, name) for name in PROMPT_VERSION_SORTABLE
}


def is_valid_prompt_version_sort(sort: str) -> bool:
    """Return True if ``sort`` targets an allowed prompt-version field."""
    return is_valid_sort(sort, PROMPT_VERSION_SORTABLE)


def list_prompt_versions(
    page: int = 1,
    limit: int = 20,
    agent_run_id: Optional[int] = None,
    q: Optional[str] = None,
    sort: str = "-created_at",
) -> tuple[list[PromptVersion], int]:
    """Return a page of prompt versions and the total matching count.

    ``q`` performs a case-insensitive search on the prompt text.
    """
    query = PromptVersion.query
    if agent_run_id is not None:
        query = query.filter(PromptVersion.agent_run_id == agent_run_id)
    if q:
        query = query.filter(PromptVersion.prompt_text.ilike(f"%{q}%"))
    total = query.count()
    query = apply_sort(query, sort, _PROMPT_VERSION_SORT_COLUMNS)
    items = query.limit(limit).offset((page - 1) * limit).all()
    return items, total
