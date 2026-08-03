"""
Purpose: Typed, read-only access to the local SQLite portfolio database (pact.db).
Every agent goes through this module rather than touching SQL/CSV directly, so
the underlying storage can change (e.g. to Postgres) without touching agent code.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager

from app import config


@contextmanager
def connection():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def _rows(sql: str, params: tuple = ()) -> list[dict]:
    with connection() as conn:
        cursor = conn.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]


def fetch_contracts() -> list[dict]:
    return _rows("SELECT * FROM contracts")


def fetch_contract(contract_id: str) -> dict | None:
    rows = _rows("SELECT * FROM contracts WHERE contract_id = ?", (contract_id,))
    return rows[0] if rows else None


def fetch_circuits(contract_id: str | None = None) -> list[dict]:
    if contract_id:
        return _rows("SELECT * FROM circuits WHERE contract_id = ?", (contract_id,))
    return _rows("SELECT * FROM circuits")


def fetch_colo(contract_id: str | None = None) -> list[dict]:
    if contract_id:
        return _rows("SELECT * FROM colo_contracts WHERE contract_id = ?", (contract_id,))
    return _rows("SELECT * FROM colo_contracts")


def fetch_licenses(contract_id: str | None = None) -> list[dict]:
    if contract_id:
        return _rows("SELECT * FROM licenses WHERE contract_id = ?", (contract_id,))
    return _rows("SELECT * FROM licenses")


def fetch_mobile_lines(contract_id: str | None = None) -> list[dict]:
    if contract_id:
        return _rows("SELECT * FROM mobile_lines WHERE contract_id = ?", (contract_id,))
    return _rows("SELECT * FROM mobile_lines")


def fetch_benchmarks() -> dict[str, float]:
    rows = _rows("SELECT category, benchmark_rate FROM benchmark_rates")
    return {row["category"]: float(row["benchmark_rate"]) for row in rows}


def fetch_child_assets(contract_id: str) -> dict[str, list[dict]]:
    """All granular assets (circuits/colo/licenses/mobile) tied to one contract."""
    return {
        "circuits": fetch_circuits(contract_id),
        "colo": fetch_colo(contract_id),
        "licenses": fetch_licenses(contract_id),
        "mobile_lines": fetch_mobile_lines(contract_id),
    }


def portfolio_totals() -> dict:
    with connection() as conn:
        total_annual = conn.execute("SELECT SUM(annual_cost) FROM contracts").fetchone()[0] or 0
        by_category = conn.execute(
            "SELECT service_type, SUM(annual_cost) AS total FROM contracts GROUP BY service_type ORDER BY total DESC"
        ).fetchall()
        counts = {
            "contracts": conn.execute("SELECT COUNT(*) FROM contracts").fetchone()[0],
            "circuits": conn.execute("SELECT COUNT(*) FROM circuits").fetchone()[0],
            "colo": conn.execute("SELECT COUNT(*) FROM colo_contracts").fetchone()[0],
            "licenses": conn.execute("SELECT COUNT(*) FROM licenses").fetchone()[0],
            "mobile_lines": conn.execute("SELECT COUNT(*) FROM mobile_lines").fetchone()[0],
        }
    return {
        "total_annual_spend": round(float(total_annual), 2),
        "total_monthly_spend": round(float(total_annual) / 12, 2),
        # row["total"] can be NULL when every contract in that service_type group
        # has no stated annual_cost - an uploaded contract whose document never
        # names a fee is a real, expected case, not just a test artifact.
        "spend_by_category": {row["service_type"]: round(float(row["total"] or 0), 2) for row in by_category},
        "asset_counts": counts,
    }


# ---------------------------------------------------------------------------
# Uploaded contracts
# ---------------------------------------------------------------------------


def ensure_source_column() -> None:
    """Add contracts.source to databases created before uploads existed, so an
    existing runtime/pact.db upgrades in place rather than needing a reseed."""
    with connection() as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(contracts)")}
        if "source" not in columns:
            conn.execute("ALTER TABLE contracts ADD COLUMN source TEXT DEFAULT 'seed'")
            conn.execute("UPDATE contracts SET source = 'seed' WHERE source IS NULL")
            conn.commit()


def upsert_upload_row(record) -> None:
    """Insert or replace the contracts row derived from an uploaded document.

    Only the columns an actual contract document can support are populated.
    Utilization-derived columns stay NULL - see the waste agent, which reports
    uploads as unavailable rather than inventing numbers for them.

    owner is set to the "Uploaded" placeholder below purely so list/detail
    views have something to display - it is not load-bearing for correctness.
    waste.py skips uploaded contracts by contract_id (via fetch_upload_ids()),
    not by checking whether owner is non-empty, so blanking or removing this
    placeholder later will not resurrect a fabricated contract_owner_gap
    finding for a document that never had utilization telemetry."""
    ensure_source_column()
    with connection() as conn:
        conn.execute("DELETE FROM contracts WHERE contract_id = ?", (record.contract_id,))
        conn.execute(
            """INSERT INTO contracts
               (contract_id, vendor, service_type, start_date, end_date, annual_cost,
                monthly_cost, auto_renew, notice_days, termination_fee_pct,
                escalation_pct, owner, status, region, minimum_commitment, source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'upload')""",
            (
                record.contract_id,
                record.vendor or "Unknown vendor",
                record.category or "Uploaded contract",
                "",
                record.renewal_date or "",
                record.annual_cost,
                record.monthly_cost,
                "Yes" if record.auto_renew else "No",
                record.notice_period_days,
                record.termination_fee_pct,
                record.annual_escalator_pct,
                "Uploaded",
                "Active",
                "",
                record.minimum_commitment or "",
            ),
        )
        conn.commit()


def delete_upload_row(contract_id: str) -> None:
    ensure_source_column()
    with connection() as conn:
        conn.execute(
            "DELETE FROM contracts WHERE contract_id = ? AND source = 'upload'",
            (contract_id,),
        )
        conn.commit()


def fetch_upload_ids() -> set[str]:
    ensure_source_column()
    return {row["contract_id"] for row in _rows("SELECT contract_id FROM contracts WHERE source = 'upload'")}
