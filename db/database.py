"""事件数据库 - SQLite 日志存储"""
import os
import sqlite3
import time
from contextlib import contextmanager

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "events.db")


class Database:
    def __init__(self, db_path=None):
        self._path = db_path or DB_PATH
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        self._init_db()

    def _init_db(self):
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    start_time REAL NOT NULL,
                    end_time REAL NOT NULL,
                    duration REAL NOT NULL,
                    peak_db REAL,
                    peak_ratio REAL,
                    source TEXT DEFAULT 'upstairs',
                    recording_path TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_start ON events(start_time)
            """)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def insert_event(self, start_time, end_time, peak_db, peak_ratio,
                     source="upstairs", recording_path=None):
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO events (start_time, end_time, duration, "
                "peak_db, peak_ratio, source, recording_path) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (start_time, end_time, end_time - start_time,
                 peak_db, peak_ratio, source, recording_path)
            )

    def get_events_today(self):
        """获取今天的事件"""
        import datetime
        today = datetime.date.today()
        start = time.mktime(today.timetuple())
        end = start + 86400
        return self._query_range(start, end)

    def get_events_range(self, start_ts, end_ts):
        return self._query_range(start_ts, end_ts)

    def _query_range(self, start, end):
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM events WHERE start_time >= ? AND start_time < ? "
                "ORDER BY start_time DESC", (start, end)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_daily_stats(self, days=7):
        """最近 N 天每日统计"""
        import datetime
        results = []
        for i in range(days):
            day = datetime.date.today() - datetime.timedelta(days=i)
            start = time.mktime(day.timetuple())
            end = start + 86400
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT COUNT(*) as cnt, "
                    "COALESCE(SUM(duration), 0) as total_dur, "
                    "COALESCE(MAX(peak_db), 0) as max_db "
                    "FROM events WHERE start_time >= ? AND start_time < ?",
                    (start, end)
                ).fetchone()
                results.append({
                    'date': day.isoformat(),
                    'count': row['cnt'],
                    'total_duration': row['total_dur'],
                    'max_db': row['max_db'],
                })
        return results

    def get_hourly_distribution(self, days=7):
        """最近 N 天按小时分布"""
        import datetime
        start = time.mktime(
            (datetime.date.today() - datetime.timedelta(days=days)).timetuple()
        )
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT start_time FROM events WHERE start_time >= ?",
                (start,)
            ).fetchall()
        hours = [0] * 24
        for r in rows:
            h = time.localtime(r['start_time']).tm_hour
            hours[h] += 1
        return hours
