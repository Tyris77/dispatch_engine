import glob
import os
import sys
import sqlite3

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.models.lead_action import LeadAction


def migrate_sqlite_databases():
    target_cols = {col.name: col for col in LeadAction.__table__.columns}
    print(f"LeadAction model specifies {len(target_cols)} columns:")
    for col_name in target_cols:
        print(f" - {col_name}")

    # Search for all SQLite database files in the repository
    db_files = set(glob.glob("**/*.db", recursive=True) + glob.glob("**/*.sqlite*", recursive=True))
    if not db_files:
        print("No .db or .sqlite files found.")
        return

    print(f"\nFound {len(db_files)} SQLite database files: {db_files}")

    for db_path in sorted(db_files):
        print(f"\n==========================================")
        print(f"Inspecting database: {db_path}")
        print(f"==========================================")
        try:
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            if "lead_actions" not in tables:
                print(f"Table 'lead_actions' not found in {db_path}. Skipping.")
                conn.close()
                continue

            existing_cols = {r[1] for r in cur.execute("PRAGMA table_info(lead_actions)").fetchall()}
            missing_cols = [c for c in target_cols if c not in existing_cols]

            print(f"Found {len(existing_cols)} existing columns in 'lead_actions'.")
            if not missing_cols:
                print("[OK] All columns already present. No schema migration needed.")
                conn.close()
                continue


            print(f"Adding {len(missing_cols)} missing columns to {db_path}:")
            for col_name in missing_cols:
                col_type = "FLOAT" if col_name == "trip_mileage" else "JSON"
                alter_query = f"ALTER TABLE lead_actions ADD COLUMN {col_name} {col_type};"
                print(f"  -> Executing: {alter_query}")
                cur.execute(alter_query)

            conn.commit()

            # Verify schema
            post_cols = {r[1] for r in cur.execute("PRAGMA table_info(lead_actions)").fetchall()}
            still_missing = [c for c in target_cols if c not in post_cols]
            if still_missing:
                print(f"[FAIL] Error: still missing columns: {still_missing}")
            else:
                print(f"[OK] Success: all {len(post_cols)} LeadAction columns verified in {db_path}.")
            conn.close()

        except Exception as exc:
            print(f"Error inspecting {db_path}: {exc}")

if __name__ == "__main__":
    migrate_sqlite_databases()
