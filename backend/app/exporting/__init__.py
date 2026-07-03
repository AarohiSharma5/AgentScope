"""Export / import subsystem (v0.6).

Exports conversations, workflows, replays, evaluations and analytics to JSON,
CSV, OpenTelemetry (OTLP/JSON), SQLite, PostgreSQL, a Zip archive or a
self-contained *Trace Bundle*; imports them back; and replays conversations from
exported traces.

Everything flows through the canonical :mod:`bundle` envelope, and formats are
resolved via an :class:`~app.exporting.exporters.ExporterRegistry`, so new
formats are added by writing an exporter/importer — the core never changes.
"""
from .bundle import (
    BundleError,
    BundleKind,
    ExportFormat,
    make_bundle,
    validate_bundle,
    verify_checksum,
)
from .exporters import Exporter, ExporterError, exporter_registry, register_exporter
from .importers import ImporterError, import_bundle_to_db, parse
from .service import (
    ExportResult,
    export_entity,
    import_data,
    inspect_data,
    list_formats,
    list_kinds,
    replay_from_export,
)

__all__ = [
    "BundleError",
    "BundleKind",
    "ExportFormat",
    "ExportResult",
    "Exporter",
    "ExporterError",
    "ImporterError",
    "export_entity",
    "exporter_registry",
    "import_bundle_to_db",
    "import_data",
    "inspect_data",
    "list_formats",
    "list_kinds",
    "make_bundle",
    "parse",
    "register_exporter",
    "replay_from_export",
    "validate_bundle",
    "verify_checksum",
]
