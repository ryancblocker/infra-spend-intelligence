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

    rehydrate_uploads()
    return counts


def rehydrate_uploads() -> int:
    """Reconcile the contracts table's uploaded rows against the manifest.

    The manifest is the durable record of an upload; the contracts row is
    derived state, so this makes the table match the manifest in both
    directions:

    - build_database() deletes the database file outright, so uploaded rows
      cannot survive a reseed on their own - each manifest entry is replayed.
    - A row for an id the manifest no longer lists is an orphan and is deleted.
      Such a row is unreachable by design: the dashboard's upload card is built
      from the manifest, so it gets no Remove button, and /api/uploads/{id}/remove
      404s on it - yet it still rendered on /contracts and still counted in
      portfolio totals and renewal risk. Derived state must not outlive the
      record it derives from.

    Returns the number of rows restored."""
    from app.agents.schemas import ExtractedContract
    from app.tools import dataset_tools, uploads

    dataset_tools.ensure_source_column()
    try:
        entries = uploads.read_manifest()["entries"]
    except uploads.ManifestError as exc:
        # No reconciliation on a corrupt manifest: "the manifest lists nothing"
        # and "the manifest could not be read" are different facts, and deleting
        # every uploaded row on the second would turn a recoverable parse failure
        # into permanent loss of the rows too.
        print(
            f"[PACT] Skipping upload rehydration - manifest at "
            f"{config.UPLOAD_MANIFEST_PATH} is corrupt: {exc}"
        )
        return 0

    restored = 0
    for entry in entries.values():
        terms = entry.get("terms")
        if not terms:
            continue
        dataset_tools.upsert_upload_row(ExtractedContract(**terms), entry.get("original_filename", ""))
        restored += 1

    for orphan_id in dataset_tools.fetch_upload_ids() - set(entries):
        print(f"[PACT] Dropping orphaned upload row {orphan_id} - no manifest entry.")
        dataset_tools.delete_upload_row(orphan_id)

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
