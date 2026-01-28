import sqlite3
import json
from datetime import datetime, date, timedelta
from typing import Optional, Dict, Any, List


class UserDatabase:
#SQLite база для Telegram-бота



    def __init__(self, db_path: str = "english_tutor.db"):
        self.db_path = db_path
        self._init_database()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _table_columns(self, conn: sqlite3.Connection, table: str) -> List[str]:
        rows = conn.execute(f"PRAGMA table_info({table});").fetchall()
        return [r["name"] for r in rows]

    def _ensure_column(self, conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
        cols = set(self._table_columns(conn, table))
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl};")

    def _init_database(self) -> None:
        with self._connect() as conn:
            cur = conn.cursor()

            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER UNIQUE NOT NULL,
                    username TEXT,
                    level TEXT DEFAULT 'beginner',
                    goal TEXT DEFAULT 'general',
                    total_exercises INTEGER DEFAULT 0,
                    correct_answers INTEGER DEFAULT 0,
                    accuracy REAL DEFAULT 0.0,
                    weak_topics TEXT DEFAULT '[]',
                    vocabulary_size INTEGER DEFAULT 0,
                    last_active TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS exercise_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    exercise_type TEXT,
                    topic TEXT,
                    question TEXT,
                    user_answer TEXT,
                    correct_answer TEXT,
                    is_correct INTEGER,
                    difficulty REAL,
                    time_spent INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS learning_plans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    daily_goal INTEGER DEFAULT 5,
                    focus_topics TEXT DEFAULT '[]',
                    progress_percentage REAL DEFAULT 0.0,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
                )
            """)

            conn.commit()

            self._ensure_column(conn, "users", "streak_days", "streak_days INTEGER DEFAULT 0")
            self._ensure_column(conn, "users", "last_exercise_date", "last_exercise_date TEXT")
            conn.commit()

    def get_user(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()
            if not row:
                return None
            user = dict(row)
            user["weak_topics"] = json.loads(user.get("weak_topics") or "[]")
            return user

    def get_or_create_user(self, telegram_id: int, username: Optional[str] = None) -> Dict[str, Any]:
        user = self.get_user(telegram_id)
        if user:
            with self._connect() as conn:
                conn.execute(
                    "UPDATE users SET username = COALESCE(?, username), last_active = ? WHERE telegram_id = ?",
                    (username, datetime.now(), telegram_id),
                )
                conn.commit()
            return self.get_user(telegram_id) or user

        with self._connect() as conn:
            conn.execute(
                "INSERT INTO users (telegram_id, username, last_active) VALUES (?, ?, ?)",
                (telegram_id, username, datetime.now()),
            )
            conn.commit()
        return self.get_user(telegram_id)  # type: ignore

    def set_user_level(self, telegram_id: int, level: str) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE users SET level = ? WHERE telegram_id = ?", (level, telegram_id))
            conn.commit()

    def _streak_update(self, last_date_str: Optional[str]) -> (int, str):
        today = date.today()
        today_str = today.isoformat()

        if not last_date_str:
            return 1, today_str

        try:
            last_date = date.fromisoformat(last_date_str)
        except Exception:
            return 1, today_str

        if last_date == today:
            return 0, today_str  # keep
        if last_date == today - timedelta(days=1):
            return 1, today_str  # increment
        return -1, today_str  # reset

    def record_exercise(
        self,
        telegram_id: int,
        exercise_type: str,
        topic: str,
        question: str,
        user_answer: str,
        correct_answer: str,
        is_correct: bool,
        difficulty: float = 0.5,
        time_spent: int = 0,
        new_level: Optional[str] = None,
    ) -> None:
        user = self.get_or_create_user(telegram_id)
        user_db_id = int(user["id"])

        total = int(user.get("total_exercises", 0) or 0) + 1
        correct = int(user.get("correct_answers", 0) or 0) + (1 if is_correct else 0)
        accuracy = (correct / total) if total else 0.0

        weak_topics = list(user.get("weak_topics", []) or [])
        if (not is_correct) and topic and (topic not in weak_topics):
            weak_topics.append(topic)
            weak_topics = weak_topics[-5:]

        streak_days = int(user.get("streak_days", 0) or 0)
        last_ex_date = user.get("last_exercise_date")
        action, today_str = self._streak_update(last_ex_date)
        if action == 0:
            new_streak = streak_days
        elif action == 1:
            new_streak = (streak_days + 1) if last_ex_date else 1
        else:
            new_streak = 1

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO exercise_history
                (user_id, exercise_type, topic, question, user_answer, correct_answer,
                 is_correct, difficulty, time_spent)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_db_id,
                    exercise_type,
                    topic,
                    question,
                    user_answer,
                    correct_answer,
                    1 if is_correct else 0,
                    float(difficulty),
                    int(time_spent),
                ),
            )

            if new_level:
                conn.execute(
                    """
                    UPDATE users
                    SET total_exercises=?,
                        correct_answers=?,
                        accuracy=?,
                        weak_topics=?,
                        level=?,
                        streak_days=?,
                        last_exercise_date=?,
                        last_active=?
                    WHERE telegram_id=?
                    """,
                    (
                        total,
                        correct,
                        float(accuracy),
                        json.dumps(weak_topics, ensure_ascii=False),
                        new_level,
                        int(new_streak),
                        today_str,
                        datetime.now(),
                        telegram_id,
                    ),
                )
            else:
                conn.execute(
                    """
                    UPDATE users
                    SET total_exercises=?,
                        correct_answers=?,
                        accuracy=?,
                        weak_topics=?,
                        streak_days=?,
                        last_exercise_date=?,
                        last_active=?
                    WHERE telegram_id=?
                    """,
                    (
                        total,
                        correct,
                        float(accuracy),
                        json.dumps(weak_topics, ensure_ascii=False),
                        int(new_streak),
                        today_str,
                        datetime.now(),
                        telegram_id,
                    ),
                )
            conn.commit()

    def get_user_stats(self, telegram_id: int) -> Dict[str, Any]:
        user = self.get_user(telegram_id)
        if not user:
            return {}

        with self._connect() as conn:
            stats_row = conn.execute(
                """
                SELECT
                    COUNT(*) as total,
                    AVG(difficulty) as avg_difficulty,
                    AVG(time_spent) as avg_time
                FROM exercise_history
                WHERE user_id = (SELECT id FROM users WHERE telegram_id = ?)
                """,
                (telegram_id,),
            ).fetchone()

        return {
            "level": user.get("level", "beginner"),
            "accuracy": float(user.get("accuracy", 0.0) or 0.0),
            "total_exercises": int(user.get("total_exercises", 0) or 0),
            "correct_answers": int(user.get("correct_answers", 0) or 0),
            "weak_topics": user.get("weak_topics", []),
            "avg_difficulty": float(stats_row["avg_difficulty"] or 0.0) if stats_row else 0.0,
            "avg_time": float(stats_row["avg_time"] or 0.0) if stats_row else 0.0,
            "streak_days": int(user.get("streak_days", 0) or 0),
        }
