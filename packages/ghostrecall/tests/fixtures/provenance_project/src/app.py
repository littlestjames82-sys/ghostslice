"""Widget service entry point (fixture code for combined bundles)."""
import sqlite3


def connect(path):
    """Open the local SQLite store."""
    return sqlite3.connect(path)


def main():
    db = connect("widget.db")
    db.execute("CREATE TABLE IF NOT EXISTS widgets (name TEXT)")
    db.commit()


if __name__ == "__main__":
    main()
