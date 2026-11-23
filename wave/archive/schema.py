import sqlite3

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS channels(
 id TEXT PRIMARY KEY,payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tasks(
 id TEXT PRIMARY KEY,channel_id TEXT NOT NULL REFERENCES channels(id),payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS delivery(
 task_id TEXT PRIMARY KEY REFERENCES tasks(id),
 frontier INTEGER NOT NULL CHECK(frontier>=0),
 ended INTEGER NOT NULL CHECK(ended IN (0,1)),
 next_index INTEGER NOT NULL CHECK(next_index>=0),
 sealed INTEGER NOT NULL CHECK(sealed IN (0,1)),
 event_count INTEGER NOT NULL CHECK(event_count>=0),
 CHECK(ended=sealed));
CREATE TABLE IF NOT EXISTS events(
 task_id TEXT NOT NULL REFERENCES tasks(id),seq INTEGER NOT NULL,
 payload TEXT NOT NULL,PRIMARY KEY(task_id,seq));
CREATE TABLE IF NOT EXISTS waveform(
 task_id TEXT NOT NULL REFERENCES tasks(id),m INTEGER NOT NULL,
 time TEXT NOT NULL,value REAL,valid INTEGER NOT NULL CHECK(valid IN (0,1)),
 PRIMARY KEY(task_id,m),CHECK((valid=0 AND value IS NULL) OR (valid=1 AND value IS NOT NULL)));
CREATE TABLE IF NOT EXISTS window_batches(
 id INTEGER PRIMARY KEY,task_id TEXT NOT NULL REFERENCES tasks(id),
 source_id TEXT NOT NULL,request TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS window_results(
 batch_id INTEGER NOT NULL REFERENCES window_batches(id),
 ordinal INTEGER NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(batch_id,ordinal));
"""

_COLUMNS = {
    "metadata": ("key", "value"),
    "channels": ("id", "payload"),
    "tasks": ("id", "channel_id", "payload"),
    "delivery": ("task_id", "frontier", "ended", "next_index", "sealed", "event_count"),
    "events": ("task_id", "seq", "payload"),
    "waveform": ("task_id", "m", "time", "value", "valid"),
    "window_batches": ("id", "task_id", "source_id", "request"),
    "window_results": ("batch_id", "ordinal", "payload"),
}


def check_schema_version(connection):
    cursor = connection.execute("SELECT value FROM metadata WHERE key='version'")
    try:
        row = cursor.fetchone()
    finally:
        cursor.close()
    if row is None or row[0] != SCHEMA_VERSION:
        raise ValueError("unsupported archive schema version")
    for table, columns in _COLUMNS.items():
        cursor = connection.execute("PRAGMA table_info(" + table + ")")
        try:
            actual = tuple(row[1] for row in cursor.fetchall())
        finally:
            cursor.close()
        if actual != columns:
            raise ValueError("archive schema mismatch: " + table)
    return SCHEMA_VERSION


def ensure_schema(connection):
    if connection.in_transaction:
        raise ValueError("initialize outside business transactions")
    connection.execute("PRAGMA foreign_keys=ON").close()
    cursor = connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='metadata'")
    try:
        existing = cursor.fetchone() is not None
    finally:
        cursor.close()
    if existing:
        return check_schema_version(connection)
    cursor = connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    try:
        if cursor.fetchone() is not None:
            raise ValueError("database is not a wave archive")
    finally:
        cursor.close()
    try:
        connection.executescript("BEGIN IMMEDIATE;\n" + _SCHEMA)
        connection.execute("INSERT INTO metadata VALUES('version',?)", (SCHEMA_VERSION,)).close()
        check_schema_version(connection)
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    return SCHEMA_VERSION
