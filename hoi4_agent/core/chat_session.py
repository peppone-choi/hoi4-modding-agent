"""
대화 세션 영구 저장 관리.
SQLite를 사용하여 대화 기록을 저장하고 복원한다.
"""
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


class ChatSessionManager:
    """대화 세션 저장/로드 관리."""

    def __init__(self, db_path: Path | str = "tools/.chat_sessions.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """DB 초기화 및 테이블 생성."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    message_count INTEGER DEFAULT 0
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    images TEXT,
                    tool_history TEXT,
                    timestamp TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_session_messages 
                ON messages(session_id, timestamp)
            """)
            # 기존 DB 마이그레이션
            self._migrate(conn)

    def _migrate(self, conn: sqlite3.Connection) -> None:
        """기존 DB에 새 컬럼을 안전하게 추가."""
        existing = {row[1] for row in conn.execute("PRAGMA table_info(messages)")}
        if "tool_history" not in existing:
            conn.execute("ALTER TABLE messages ADD COLUMN tool_history TEXT")

    def create_session(self, title: str | None = None) -> str:
        """새 세션 생성."""
        session_id = datetime.now().strftime("chat_%Y%m%d_%H%M%S")
        title = title or f"대화 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        now = datetime.now().isoformat()

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO sessions VALUES (?, ?, ?, ?, 0)",
                (session_id, title, now, now),
            )
        return session_id

    def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        images: list[str] | None = None,
        tool_history: list[dict] | None = None,
    ) -> None:
        """메시지 저장."""
        now = datetime.now().isoformat()
        images_json = json.dumps(images) if images else None
        tool_json = json.dumps(tool_history, ensure_ascii=False) if tool_history else None

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO messages (session_id, role, content, images, tool_history, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                (session_id, role, content, images_json, tool_json, now),
            )
            # 세션 업데이트
            conn.execute(
                "UPDATE sessions SET updated_at = ?, message_count = message_count + 1 WHERE session_id = ?",
                (now, session_id),
            )

    def load_messages(self, session_id: str) -> list[dict[str, Any]]:
        """세션의 모든 메시지 로드."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT role, content, images, tool_history FROM messages WHERE session_id = ? ORDER BY timestamp",
                (session_id,),
            )
            messages = []
            for row in cursor:
                msg = {"role": row["role"], "content": row["content"]}
                if row["images"]:
                    msg["images"] = json.loads(row["images"])
                if row["tool_history"]:
                    msg["tool_history"] = json.loads(row["tool_history"])
                messages.append(msg)
            return messages

    def list_sessions(self, limit: int = 50) -> list[dict[str, Any]]:
        """세션 목록 조회."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT session_id, title, created_at, updated_at, message_count FROM sessions ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            )
            return [dict(row) for row in cursor]

    def delete_session(self, session_id: str) -> None:
        """세션 삭제."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))

    def update_session_title(self, session_id: str, title: str) -> None:
        """세션 제목 변경."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE sessions SET title = ?, updated_at = ? WHERE session_id = ?",
                (title, datetime.now().isoformat(), session_id),
            )

    def get_latest_session(self) -> str | None:
        """가장 최근 세션 ID 반환."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT session_id FROM sessions ORDER BY updated_at DESC LIMIT 1"
            )
            row = cursor.fetchone()
            return row[0] if row else None

    def search_messages(self, query: str, session_id: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        """세션 메시지 전문 검색."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if session_id:
                cursor = conn.execute(
                    "SELECT m.session_id, s.title, m.role, m.content, m.timestamp "
                    "FROM messages m JOIN sessions s ON m.session_id = s.session_id "
                    "WHERE m.session_id = ? AND m.content LIKE ? "
                    "ORDER BY m.timestamp DESC LIMIT ?",
                    (session_id, f"%{query}%", limit),
                )
            else:
                cursor = conn.execute(
                    "SELECT m.session_id, s.title, m.role, m.content, m.timestamp "
                    "FROM messages m JOIN sessions s ON m.session_id = s.session_id "
                    "WHERE m.content LIKE ? "
                    "ORDER BY m.timestamp DESC LIMIT ?",
                    (f"%{query}%", limit),
                )
            return [dict(row) for row in cursor]
