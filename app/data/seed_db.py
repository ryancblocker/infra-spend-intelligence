"""
Purpose: Build the runtime SQLite database and Chroma vector index from the CSV/text
seed fixtures under app/data/seed/ and app/data/contract_docs/.

Run: python -m app.data.seed_db [--check]
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app import config  # noqa: E402

TABLE_SPECS = {
    "contracts": "contracts.csv",
    "circuits": "circuits.csv",
    "colo_contracts": "colo_contracts.csv",
    "licenses": "licenses.csv",
    "mobile_lines": "mobile_lines.csv",
    "benchmark_rates": "benchmark_rates.csv",
}


def build_database() -> dict[str, int]:
    config.ensure_runtime_dirs()
    if config.DB_PATH.exists():
        config.DB_PATH.unlink()

    conn = sqlite3.connect(config.DB_PATH)
    counts: dict[str, int] = {}
    try:
        for table, filename in TABLE_SPECS.items():
            csv_path = config.SEED_DIR / filename
            df = pd.read_csv(csv_path, comment="#")
            df.to_sql(table, conn, if_exists="replace", index=False)
            counts[table] = len(df)
        conn.commit()
    finally:
        conn.close()

    _rehydrate_uploads()
    return counts


def _rehydrate_uploads() -> int:
    """Re-create contracts rows for uploaded documents.

    build_database() deletes the database file outright, so uploaded rows cannot
    survive a reseed on their own. runtime/uploads/manifest.json is the durable
    record; this replays it. Returns the number of rows restored."""
    from app.agents.schemas import ExtractedContract
    from app.tools import dataset_tools, uploads

    dataset_tools.ensure_source_column()
    restored = 0
    for entry in uploads.read_manifest()["entries"].values():
        terms = entry.get("terms")
        if not terms:
            continue
        dataset_tools.upsert_upload_row(ExtractedContract(**terms))
        restored += 1
    return restored


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Print summary stats without exhaustive detail")
    parser.add_argument("--skip-vectors", action="store_true", help="Skip vector index build (faster, no embeddings)")
    args = parser.parse_args()

    counts = build_database()
    print("SQLite tables built:")
    for table, n in counts.items():
        print(f"  {table}: {n} rows")

    if not args.skip_vectors:
        try:
            from app.tools.vector_store import build_index

            n_docs = build_index()
            print(f"Vector index built: {n_docs} contract documents chunked and embedded")
        except Exception as exc:  # pragma: no cover - depends on optional embedding backend
            print(f"[WARN] Vector index build skipped: {exc}")

    if args.check:
        conn = sqlite3.connect(config.DB_PATH)
        total_annual = conn.execute("SELECT SUM(annual_cost) FROM contracts").fetchone()[0]
        conn.close()
        print(f"Sanity check - total annual contract spend: ${total_annual:,.0f}")


if __name__ == "__main__":
    main()
