"""Load the read-only seed CSVs into `app.db`, the SQLite file the MCP server reads.

One command -- `uv run python load_seed.py` -- turns `seed/tickets.csv` and
`seed/customers.csv` into the `tickets` and `customers` tables that
`mcp/triage_server.py` selects from by name. Nothing here touches the network or
needs a key, and it adds no dependency: the stdlib `csv` and `sqlite3` are enough.

Two properties matter and are built in rather than tested for afterwards:

* **Repeatable.** Every run builds the database from scratch, so running the
  loader twice leaves exactly the same rows -- no duplicates, and no stale rows
  left over from an earlier seed file.
* **All-or-nothing.** Both CSVs are read and fully validated before any database
  work starts, and the work happens in a scratch file that is moved over
  `app.db` only once it is complete. A bad seed file therefore leaves the
  previous `app.db` untouched, and leaves no `app.db` at all if there was none:
  `mcp/triage_server.py` guards only on the file existing, so a half-built one
  would turn its "load the data first" message into a bare "no such table".

Paths resolve from this file's own location, not the working directory, so the
command behaves the same wherever it is invoked from.
"""

from __future__ import annotations

import csv
import os
import sqlite3
import sys
from pathlib import Path

__all__ = ["DB_PATH", "SEED_DIR", "load_seed", "main"]

ROOT = Path(__file__).resolve().parent
SEED_DIR = ROOT / "seed"
DB_PATH = ROOT / "app.db"

TICKET_COLUMNS = ("ticket_id", "customer_id", "created_at", "text")
CUSTOMER_COLUMNS = ("customer_id", "name", "plan", "open_tickets")


def _read_csv(path: Path, columns: tuple[str, ...]) -> list[dict[str, str]]:
    """Return every row of `path` as a dict, or raise naming the file and the bad row.

    Validation lives here, before any database is opened, so that malformed seed
    data fails with an explanation instead of a raw sqlite3 constraint error.
    """
    if not path.exists():
        raise FileNotFoundError(f"Seed file not found: {path}")
    # utf-8-sig so a seed file saved with a BOM does not make the first column
    # look absent.
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        missing = [column for column in columns if column not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{path} is missing the column(s) {', '.join(missing)}")
        rows = list(reader)

    if not rows:
        raise ValueError(f"{path} has a header but no data rows; refusing to empty the database")

    id_column = columns[0]
    seen: set[str] = set()
    for row in rows:
        row_id = row.get(id_column)
        for column in columns:
            value = row.get(column)
            if value is None or not value.strip():
                raise ValueError(
                    f"{path}: row {row_id!r} has an empty {column}; every column is required"
                )
        if row_id in seen:
            raise ValueError(f"{path}: duplicate {id_column} {row_id!r}; ids must be unique")
        seen.add(row_id)
    return rows


def _ticket_rows(path: Path) -> list[tuple[str, ...]]:
    return [tuple(row[column] for column in TICKET_COLUMNS) for row in _read_csv(path, TICKET_COLUMNS)]


def _customer_rows(path: Path) -> list[tuple[str, str, str, int]]:
    rows = []
    for row in _read_csv(path, CUSTOMER_COLUMNS):
        try:
            open_tickets = int(row["open_tickets"])
        except ValueError:
            raise ValueError(
                f"{path}: customer {row['customer_id']!r} has a non-numeric open_tickets "
                f"value {row['open_tickets']!r}; it must be a whole number so the policy's "
                f"'3 or more open tickets' rule can compare numerically"
            ) from None
        rows.append((row["customer_id"], row["name"], row["plan"], open_tickets))
    return rows


def _write_database(path: Path, tickets: list[tuple[str, ...]], customers: list[tuple[str, str, str, int]]) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            CREATE TABLE tickets (
                ticket_id   TEXT PRIMARY KEY,
                customer_id TEXT NOT NULL,
                created_at  TEXT NOT NULL,
                text        TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE customers (
                customer_id  TEXT PRIMARY KEY,
                name         TEXT NOT NULL,
                plan         TEXT NOT NULL,
                open_tickets INTEGER NOT NULL
            )
            """
        )
        conn.executemany("INSERT INTO tickets VALUES (?, ?, ?, ?)", tickets)
        conn.executemany("INSERT INTO customers VALUES (?, ?, ?, ?)", customers)
        conn.commit()
    finally:
        conn.close()


def load_seed(db_path: Path | str = DB_PATH, seed_dir: Path | str = SEED_DIR) -> tuple[int, int]:
    """Load both seed CSVs into `db_path`, replacing any previous contents.

    Returns the number of ticket rows and customer rows written.
    """
    seed_dir = Path(seed_dir)
    db_path = Path(db_path)

    # Read and validate everything first: nothing below can start on bad data.
    tickets = _ticket_rows(seed_dir / "tickets.csv")
    customers = _customer_rows(seed_dir / "customers.csv")

    # Build beside the target, then move it into place, so `db_path` only ever
    # holds a complete database -- a failure leaves any previous one as it was.
    scratch = db_path.with_name(f".{db_path.name}.{os.getpid()}.tmp")
    scratch.unlink(missing_ok=True)
    try:
        _write_database(scratch, tickets, customers)
        os.replace(scratch, db_path)
    except BaseException:
        scratch.unlink(missing_ok=True)
        raise

    return len(tickets), len(customers)


def main() -> int:
    try:
        ticket_count, customer_count = load_seed()
    except (FileNotFoundError, ValueError, sqlite3.Error) as error:
        print(f"Seed load failed: {error}", file=sys.stderr)
        return 1
    print(f"Loaded {ticket_count} tickets and {customer_count} customers into {DB_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
