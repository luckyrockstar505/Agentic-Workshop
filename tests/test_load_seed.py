"""One test per row of story 1.2's I/O & Edge-Case Matrix, plus the failure paths.

Every test loads into a temporary database rather than the repo's `app.db`:
running the suite must never rebuild a developer's working database, and CI has
no `app.db` at all. The `repo_database_untouched` autouse fixture enforces that
rather than trusting it. The two checks against the real file live in the
story's Verification commands instead.

The "server can read it" test imports `mcp/triage_server.py` from its path and
calls its tools, rather than copying its SQL into this file -- copied SQL would
drift along with the loader while the real server broke.
"""

import contextlib
import importlib.util
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from load_seed import DB_PATH, SEED_DIR, load_seed

EXPECTED_TICKETS = 24
EXPECTED_CUSTOMERS = 20
ROOT = Path(__file__).resolve().parent.parent
TRIAGE_SERVER = ROOT / "mcp" / "triage_server.py"


@pytest.fixture(autouse=True)
def repo_database_untouched():
    """Fail any test that lets the loader's defaults reach the repo's real app.db."""

    def state():
        return (DB_PATH.exists(), DB_PATH.stat().st_mtime_ns if DB_PATH.exists() else None)

    before = state()
    yield
    assert state() == before, f"a test created or rewrote the repo's real database at {DB_PATH}"


@pytest.fixture
def db(tmp_path):
    """A temporary database path -- never the repo's app.db."""
    return tmp_path / "app.db"


def _dump(db_path):
    """Full contents of both tables, in a stable order, for equality comparison."""
    # closing(), not sqlite3's context manager: that one commits but leaves the
    # handle open, and an open handle blocks unlinking the temp file on Windows.
    with contextlib.closing(sqlite3.connect(db_path)) as conn:
        return {
            "tickets": conn.execute("SELECT * FROM tickets ORDER BY ticket_id").fetchall(),
            "customers": conn.execute("SELECT * FROM customers ORDER BY customer_id").fetchall(),
        }


def _columns(db_path, table):
    with contextlib.closing(sqlite3.connect(db_path)) as conn:
        return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]


def _seed_dir(tmp_path, name="seed", tickets=None, customers=None):
    """A seed directory holding the real CSVs, with either file optionally overridden."""
    seed_dir = tmp_path / name
    seed_dir.mkdir()
    for filename, override in (("tickets.csv", tickets), ("customers.csv", customers)):
        text = (SEED_DIR / filename).read_text(encoding="utf-8") if override is None else override
        (seed_dir / filename).write_text(text, encoding="utf-8", newline="")
    return seed_dir


def _tickets_csv_with_duplicate_id():
    lines = (SEED_DIR / "tickets.csv").read_text(encoding="utf-8").splitlines()
    return "\n".join(lines + [lines[1]]) + "\n"


def _import_triage_server(db_path, monkeypatch):
    """Import mcp/triage_server.py by path and point it at a temporary database."""
    spec = importlib.util.spec_from_file_location("triage_server_under_test", TRIAGE_SERVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "DB_PATH", Path(db_path))
    return module


def test_fresh_load_creates_both_tables_with_the_expected_rows(db):
    assert not db.exists()

    ticket_count, customer_count = load_seed(db)

    assert (ticket_count, customer_count) == (EXPECTED_TICKETS, EXPECTED_CUSTOMERS)
    assert db.exists()
    contents = _dump(db)
    assert len(contents["tickets"]) == EXPECTED_TICKETS
    assert len(contents["customers"]) == EXPECTED_CUSTOMERS


def test_column_names_match_what_the_mcp_server_selects(db):
    load_seed(db)

    assert _columns(db, "tickets") == ["ticket_id", "customer_id", "created_at", "text"]
    assert _columns(db, "customers") == ["customer_id", "name", "plan", "open_tickets"]


def test_second_run_leaves_identical_contents(db):
    load_seed(db)
    first = _dump(db)

    assert load_seed(db) == (EXPECTED_TICKETS, EXPECTED_CUSTOMERS)

    assert _dump(db) == first
    assert len(_dump(db)["tickets"]) == EXPECTED_TICKETS


def test_reload_removes_rows_that_are_not_in_the_seed(db):
    """Recreating, not upserting: anything not in the CSVs is gone after a reload."""
    load_seed(db)
    with contextlib.closing(sqlite3.connect(db)) as conn:
        conn.execute("INSERT INTO tickets VALUES ('T-9999', 'C-77', '2026-09-09T09:09:00', 'stale')")
        conn.commit()

    load_seed(db)

    with contextlib.closing(sqlite3.connect(db)) as conn:
        assert conn.execute("SELECT * FROM tickets WHERE ticket_id = 'T-9999'").fetchone() is None
    assert len(_dump(db)["tickets"]) == EXPECTED_TICKETS


def test_quoted_comma_field_loads_as_one_intact_value(db):
    load_seed(db)

    with contextlib.closing(sqlite3.connect(db)) as conn:
        text = conn.execute("SELECT text FROM tickets WHERE ticket_id = 'T-1047'").fetchone()[0]

    assert text == "Refund the duplicate charge, please."


def test_open_tickets_is_an_integer_that_compares_numerically(db):
    load_seed(db)

    with contextlib.closing(sqlite3.connect(db)) as conn:
        values = [row[0] for row in conn.execute("SELECT open_tickets FROM customers")]
        at_threshold = conn.execute(
            "SELECT customer_id, plan FROM customers WHERE open_tickets >= 3 ORDER BY customer_id"
        ).fetchall()

    assert all(isinstance(value, int) for value in values)
    # The policy's Enterprise rule: 3 or more open tickets.
    assert at_threshold == [("C-05", "Enterprise"), ("C-66", "Enterprise"), ("C-88", "Enterprise"), ("C-91", "Enterprise")]


def test_the_mcp_server_can_serve_what_was_loaded(db, monkeypatch):
    load_seed(db)
    server = _import_triage_server(db, monkeypatch)

    ticket = server.get_ticket("T-1042")
    customer = server.get_customer_history(ticket["customer_id"])

    assert ticket["customer_id"] == "C-77"
    assert ticket["created_at"] == "2026-09-01T09:14:00"
    assert customer["name"] == "Northwind"
    assert customer["plan"] == "Enterprise"
    assert customer["open_tickets"] == 2
    # The server's query has no ORDER BY, so compare the ids as a set.
    assert sorted(customer["ticket_ids"]) == ["T-1042", "T-1047"]


def test_missing_seed_file_names_it_and_leaves_no_database(tmp_path):
    seed_dir = tmp_path / "seed"
    seed_dir.mkdir()
    shutil.copy(SEED_DIR / "customers.csv", seed_dir / "customers.csv")
    db = tmp_path / "app.db"

    with pytest.raises(FileNotFoundError) as exc:
        load_seed(db, seed_dir)

    assert str(seed_dir / "tickets.csv") in str(exc.value)
    assert not db.exists()


def test_a_failed_reload_leaves_the_previous_database_intact(tmp_path, db):
    """The target file is replaced only by a complete database, never a half-built one."""
    load_seed(db, _seed_dir(tmp_path, "good"))
    before = _dump(db)

    broken = _seed_dir(tmp_path, "broken", tickets=_tickets_csv_with_duplicate_id())
    with pytest.raises(ValueError) as exc:
        load_seed(db, broken)

    message = str(exc.value)
    assert "T-1042" in message
    assert str(broken / "tickets.csv") in message
    assert _dump(db) == before
    assert not list(db.parent.glob(".app.db.*.tmp"))


def test_a_failure_after_the_database_is_opened_leaves_nothing_behind(db, monkeypatch):
    """Nothing reaches `db_path` until a complete database is ready to move into place.

    The duplicate-id case above is caught before sqlite3 is ever opened, so this
    one forces a failure on the far side of that, where a loader that wrote
    straight to the target would leave a file `triage_server._query` would
    accept and then fail on with "no such table".
    """

    def boom(*args, **kwargs):
        raise OSError("move failed")

    monkeypatch.setattr("os.replace", boom)

    with pytest.raises(OSError):
        load_seed(db)

    assert not db.exists()
    assert not list(db.parent.glob(".app.db.*.tmp"))


def test_a_row_with_an_empty_cell_is_rejected_by_name(tmp_path, db):
    lines = (SEED_DIR / "tickets.csv").read_text(encoding="utf-8").splitlines()
    lines[1] = "T-1042,,2026-09-01T09:14:00,I was charged twice this month."
    seed_dir = _seed_dir(tmp_path, tickets="\n".join(lines) + "\n")

    with pytest.raises(ValueError) as exc:
        load_seed(db, seed_dir)

    message = str(exc.value)
    assert str(seed_dir / "tickets.csv") in message
    assert "T-1042" in message
    assert "customer_id" in message
    assert not db.exists()


def test_a_header_only_seed_file_is_rejected_rather_than_emptying_the_database(tmp_path, db):
    seed_dir = _seed_dir(tmp_path, tickets="ticket_id,customer_id,created_at,text\n")

    with pytest.raises(ValueError) as exc:
        load_seed(db, seed_dir)

    assert str(seed_dir / "tickets.csv") in str(exc.value)
    assert not db.exists()


def test_a_missing_column_names_the_file(tmp_path, db):
    seed_dir = _seed_dir(tmp_path, customers="customer_id,name,plan\nC-77,Northwind,Enterprise\n")

    with pytest.raises(ValueError) as exc:
        load_seed(db, seed_dir)

    message = str(exc.value)
    assert str(seed_dir / "customers.csv") in message
    assert "open_tickets" in message
    assert not db.exists()


def test_non_numeric_open_tickets_names_the_file_and_the_customer(tmp_path, db):
    seed_dir = _seed_dir(
        tmp_path, customers="customer_id,name,plan,open_tickets\nC-77,Northwind,Enterprise,many\n"
    )

    with pytest.raises(ValueError) as exc:
        load_seed(db, seed_dir)

    message = str(exc.value)
    assert str(seed_dir / "customers.csv") in message
    assert "C-77" in message
    assert "many" in message
    assert not db.exists()


def test_a_seed_file_with_a_byte_order_mark_still_loads(tmp_path, db):
    raw = (SEED_DIR / "tickets.csv").read_text(encoding="utf-8")
    seed_dir = _seed_dir(tmp_path, tickets="﻿" + raw)

    assert load_seed(db, seed_dir) == (EXPECTED_TICKETS, EXPECTED_CUSTOMERS)

    with contextlib.closing(sqlite3.connect(db)) as conn:
        assert conn.execute("SELECT customer_id FROM tickets WHERE ticket_id = 'T-1042'").fetchone() == ("C-77",)


def _run_loader(project, cwd):
    return subprocess.run(
        [sys.executable, str(project / "load_seed.py")],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _project_copy(tmp_path, with_tickets=True):
    """A standalone copy of the loader and its seed dir, so the subprocess stays off the repo."""
    project = tmp_path / "project"
    (project / "seed").mkdir(parents=True)
    shutil.copy(ROOT / "load_seed.py", project / "load_seed.py")
    names = ("tickets.csv", "customers.csv") if with_tickets else ("customers.csv",)
    for name in names:
        shutil.copy(SEED_DIR / name, project / "seed" / name)
    return project


def test_running_from_another_directory_loads_beside_the_script(tmp_path):
    """Paths resolve from the script's own location, not the working directory."""
    project = _project_copy(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    result = _run_loader(project, cwd=elsewhere)

    assert result.returncode == 0, result.stderr
    assert "24 tickets and 20 customers" in result.stdout
    assert not (elsewhere / "app.db").exists()
    contents = _dump(project / "app.db")
    assert len(contents["tickets"]) == EXPECTED_TICKETS
    assert len(contents["customers"]) == EXPECTED_CUSTOMERS


def test_the_command_reports_a_bad_seed_and_exits_nonzero(tmp_path):
    project = _project_copy(tmp_path, with_tickets=False)

    result = _run_loader(project, cwd=project)

    assert result.returncode == 1
    assert "Seed load failed" in result.stderr
    assert str(project / "seed" / "tickets.csv") in result.stderr
    assert result.stdout == ""
    assert not (project / "app.db").exists()
