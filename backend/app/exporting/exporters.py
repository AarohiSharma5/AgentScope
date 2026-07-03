"""Exporters: render a :mod:`bundle` into a concrete wire format.

Each exporter declares its ``format`` id, MIME ``content_type``, file
``extension`` and whether it is ``binary``, and implements ``export(bundle) ->
bytes``. They self-register with the module-level :data:`exporter_registry`, so
a new format is added by writing an exporter and registering it — the routes,
service façade and everything else discover it automatically (no core changes).
"""
from __future__ import annotations

import csv
import io
import json
import os
import sqlite3
import tempfile
import zipfile
from abc import ABC, abstractmethod
from typing import Optional

from . import collect
from .bundle import BundleKind, ExportFormat
from .otel import conversation_to_otel


class ExporterError(Exception):
    """Raised when a bundle cannot be rendered to a format."""


# -- Base + registry --------------------------------------------------------


class Exporter(ABC):
    format: str = ""
    content_type: str = "application/octet-stream"
    extension: str = "bin"
    binary: bool = False
    description: str = ""

    @abstractmethod
    def export(self, bundle: dict) -> bytes:
        """Render ``bundle`` to bytes."""

    def info(self) -> dict:
        return {
            "format": self.format,
            "content_type": self.content_type,
            "extension": self.extension,
            "binary": self.binary,
            "description": self.description,
        }


class ExporterRegistry:
    """Registry of exporters keyed by format id."""

    def __init__(self) -> None:
        self._exporters: dict[str, Exporter] = {}

    def register(self, exporter: Exporter) -> Exporter:
        self._exporters[exporter.format] = exporter
        return exporter

    def get(self, fmt: str) -> Exporter:
        if fmt not in self._exporters:
            raise ExporterError(f"unknown export format: {fmt!r}")
        return self._exporters[fmt]

    def formats(self) -> list[str]:
        return sorted(self._exporters)

    def describe(self) -> list[dict]:
        return [self._exporters[f].info() for f in self.formats()]


exporter_registry = ExporterRegistry()


def register_exporter(exporter: Exporter) -> Exporter:
    """Register an exporter instance with the default registry."""
    return exporter_registry.register(exporter)


# -- Helpers ----------------------------------------------------------------


def _dumps(value) -> bytes:
    return json.dumps(value, indent=2, default=str).encode("utf-8")


def _cell(value) -> str:
    """Render a cell value for CSV/SQL: JSON-encode structures, str otherwise."""
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, default=str)
    return str(value)


def _columns(rows: list[dict]) -> list[str]:
    """Ordered union of keys across ``rows`` (first-seen order)."""
    columns: list[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    return columns


def _ident(name: str) -> str:
    """Sanitize a string into a safe SQL identifier."""
    safe = "".join(c if c.isalnum() or c == "_" else "_" for c in str(name))
    if not safe or safe[0].isdigit():
        safe = f"t_{safe}"
    return safe


# -- JSON / OTel ------------------------------------------------------------


class JsonExporter(Exporter):
    format = ExportFormat.JSON
    content_type = "application/json"
    extension = "json"
    description = "Full bundle (manifest + payload) as pretty JSON."

    def export(self, bundle: dict) -> bytes:
        return _dumps(bundle)


class OtelExporter(Exporter):
    format = ExportFormat.OTEL
    content_type = "application/json"
    extension = "otel.json"
    description = "OpenTelemetry OTLP/JSON spans (GenAI semantic conventions)."

    def export(self, bundle: dict) -> bytes:
        return _dumps(conversation_to_otel(bundle))


# -- CSV --------------------------------------------------------------------


class CsvExporter(Exporter):
    format = ExportFormat.CSV
    content_type = "text/csv"
    extension = "csv"
    description = "Flattened primary table as CSV."

    def export(self, bundle: dict) -> bytes:
        tables = collect.tables_for(bundle)
        kind = bundle["manifest"]["kind"]
        primary = collect.PRIMARY_TABLE.get(kind)
        rows = tables.get(primary) or next(iter(tables.values()), [])
        return self._csv(rows)

    @staticmethod
    def _csv(rows: list[dict]) -> bytes:
        buffer = io.StringIO()
        columns = _columns(rows)
        writer = csv.writer(buffer)
        writer.writerow(columns or ["(empty)"])
        for row in rows:
            writer.writerow([_cell(row.get(col)) for col in columns])
        return buffer.getvalue().encode("utf-8")


# -- SQLite -----------------------------------------------------------------


class SqliteExporter(Exporter):
    format = ExportFormat.SQLITE
    content_type = "application/x-sqlite3"
    extension = "sqlite"
    binary = True
    description = "Self-contained SQLite database of the bundle's tables."

    def export(self, bundle: dict) -> bytes:
        tables = collect.tables_for(bundle)
        manifest = bundle["manifest"]
        # A real (temp) file DB is the most portable way to obtain the bytes.
        handle, path = tempfile.mkstemp(suffix=".sqlite")
        os.close(handle)
        try:
            connection = sqlite3.connect(path)
            try:
                self._write(connection, manifest, tables)
                connection.commit()
            finally:
                connection.close()
            with open(path, "rb") as fh:
                return fh.read()
        finally:
            os.unlink(path)

    @staticmethod
    def _write(connection, manifest: dict, tables: dict) -> None:
        cursor = connection.cursor()
        cursor.execute("CREATE TABLE _manifest (key TEXT, value TEXT)")
        cursor.executemany(
            "INSERT INTO _manifest (key, value) VALUES (?, ?)",
            [(k, _cell(v)) for k, v in manifest.items()],
        )
        for name, rows in tables.items():
            if not rows:
                continue
            table = _ident(name)
            columns = _columns(rows)
            column_defs = ", ".join(f'"{_ident(c)}" TEXT' for c in columns)
            cursor.execute(f'CREATE TABLE "{table}" ({column_defs})')
            placeholders = ", ".join("?" for _ in columns)
            cursor.executemany(
                f'INSERT INTO "{table}" VALUES ({placeholders})',
                [[_cell(row.get(c)) for c in columns] for row in rows],
            )


# -- PostgreSQL -------------------------------------------------------------


class PostgresExporter(Exporter):
    format = ExportFormat.POSTGRES
    content_type = "application/sql"
    extension = "sql"
    description = "PostgreSQL-compatible schema + INSERT dump of the bundle's tables."

    def export(self, bundle: dict) -> bytes:
        tables = collect.tables_for(bundle)
        manifest = bundle["manifest"]
        lines = [
            "-- AgentScope export (PostgreSQL dialect)",
            f"-- kind: {manifest.get('kind')}  entity_id: {manifest.get('entity_id')}",
            f"-- exported_at: {manifest.get('exported_at')}",
            "BEGIN;",
        ]
        for name, rows in tables.items():
            if not rows:
                continue
            lines.extend(self._table_sql(name, rows))
        lines.append("COMMIT;")
        return ("\n".join(lines) + "\n").encode("utf-8")

    @staticmethod
    def _table_sql(name: str, rows: list[dict]) -> list[str]:
        table = _ident(name)
        columns = _columns(rows)
        column_defs = ",\n  ".join(f'"{_ident(c)}" TEXT' for c in columns)
        out = [
            "",
            f'DROP TABLE IF EXISTS "{table}";',
            f'CREATE TABLE "{table}" (\n  {column_defs}\n);',
        ]
        column_list = ", ".join(f'"{_ident(c)}"' for c in columns)
        for row in rows:
            values = ", ".join(_sql_literal(row.get(c)) for c in columns)
            out.append(f'INSERT INTO "{table}" ({column_list}) VALUES ({values});')
        return out


def _sql_literal(value) -> str:
    """Render a Python value as a PostgreSQL literal."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return repr(value)
    text = _cell(value)
    return "'" + text.replace("'", "''") + "'"


# -- Zip archive ------------------------------------------------------------


class ZipExporter(Exporter):
    format = ExportFormat.ZIP
    content_type = "application/zip"
    extension = "zip"
    binary = True
    description = "Zip archive containing the JSON bundle and a manifest."

    def export(self, bundle: dict) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", _dumps(bundle["manifest"]))
            archive.writestr("bundle.json", _dumps(bundle))
            archive.writestr("README.txt", self._readme(bundle))
        return buffer.getvalue()

    @staticmethod
    def _readme(bundle: dict) -> str:
        manifest = bundle["manifest"]
        return (
            "AgentScope export archive\n"
            f"kind: {manifest.get('kind')}\n"
            f"entity_id: {manifest.get('entity_id')}\n"
            f"exported_at: {manifest.get('exported_at')}\n"
            "\nContains bundle.json (import with POST /api/import).\n"
        )


# -- Trace Bundle (the flagship, self-describing archive) -------------------


class TraceBundleExporter(Exporter):
    format = ExportFormat.BUNDLE
    content_type = "application/zip"
    extension = "agentscope.zip"
    binary = True
    description = (
        "Self-contained Trace Bundle: JSON bundle + tabular CSVs + SQLite + "
        "OpenTelemetry spans; re-importable and replayable."
    )

    def export(self, bundle: dict) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", _dumps(bundle["manifest"]))
            archive.writestr("bundle.json", _dumps(bundle))
            archive.writestr("data.sqlite", SqliteExporter().export(bundle))
            self._add_csvs(archive, bundle)
            if bundle["manifest"]["kind"] == BundleKind.CONVERSATION:
                archive.writestr("trace.otel.json", OtelExporter().export(bundle))
        return buffer.getvalue()

    @staticmethod
    def _add_csvs(archive: zipfile.ZipFile, bundle: dict) -> None:
        for name, rows in collect.tables_for(bundle).items():
            if rows:
                archive.writestr(f"tables/{_ident(name)}.csv", CsvExporter._csv(rows))


def _register_builtin_exporters() -> None:
    for exporter in (
        JsonExporter(),
        CsvExporter(),
        OtelExporter(),
        SqliteExporter(),
        PostgresExporter(),
        ZipExporter(),
        TraceBundleExporter(),
    ):
        register_exporter(exporter)


_register_builtin_exporters()
