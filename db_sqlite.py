"""
SageAlpha.ai v3.0 - SQLite Database Layer
Drop-in replacement for db.py (PostgreSQL) using SQLite.
Exposes the same public API for seamless switching.
"""

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Optional

from werkzeug.security import check_password_hash, generate_password_hash

# ==================== Database Configuration ====================
# Detect Azure App Service environment
IS_PRODUCTION = os.environ.get("WEBSITE_SITE_NAME") is not None

if IS_PRODUCTION:
    # Azure App Service persistent storage
    DB_PATH = "/home/data/sagealpha.db"
    # Ensure directory exists
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
else:
    # Local development
    DB_PATH = os.path.join(os.path.dirname(__file__) or ".", "sagealpha.db")


# ==================== SQL Placeholder Conversion ====================
def _convert_sql(sql: str) -> str:
    """
    Convert psycopg2-style %s placeholders to SQLite ? placeholders.
    This allows the rest of the codebase to use %s everywhere.
    """
    return sql.replace("%s", "?")


# ==================== Cursor Wrapper ====================
class SQLiteCursorWrapper:
    """
    Wrapper around sqlite3.Cursor that converts %s to ? placeholders.
    Also provides fetchone/fetchall that return dict-like Row objects.
    """
    
    def __init__(self, cursor: sqlite3.Cursor):
        self._cursor = cursor
    
    def execute(self, sql: str, params: tuple = None) -> "SQLiteCursorWrapper":
        """Execute SQL with automatic placeholder conversion."""
        converted_sql = _convert_sql(sql)
        if params is None:
            self._cursor.execute(converted_sql)
        else:
            self._cursor.execute(converted_sql, params)
        return self
    
    def executemany(self, sql: str, params_list: list) -> "SQLiteCursorWrapper":
        """Execute SQL for multiple parameter sets."""
        converted_sql = _convert_sql(sql)
        self._cursor.executemany(converted_sql, params_list)
        return self
    
    def fetchone(self) -> Optional[sqlite3.Row]:
        """Fetch one row."""
        return self._cursor.fetchone()
    
    def fetchall(self) -> list:
        """Fetch all rows."""
        return self._cursor.fetchall()
    
    def fetchmany(self, size: int = None) -> list:
        """Fetch many rows."""
        if size is None:
            return self._cursor.fetchmany()
        return self._cursor.fetchmany(size)
    
    @property
    def lastrowid(self) -> int:
        """Get last inserted row ID."""
        return self._cursor.lastrowid
    
    @property
    def rowcount(self) -> int:
        """Get number of affected rows."""
        return self._cursor.rowcount
    
    @property
    def description(self) -> tuple:
        """Get column descriptions."""
        return self._cursor.description
    
    def close(self) -> None:
        """Close the cursor."""
        self._cursor.close()
    
    def __iter__(self):
        """Allow iteration over results."""
        return iter(self._cursor)


# ==================== Connection Functions ====================
def get_db_connection() -> sqlite3.Connection:
    """
    Get a new database connection.
    Returns a sqlite3 connection with Row factory for dict-like access.
    
    Usage:
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM users")
            rows = cur.fetchall()
        finally:
            conn.close()
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # Rows behave like dicts
    return conn


@contextmanager
def db_cursor(commit: bool = True):
    """
    Context manager for database operations with auto commit/rollback.
    
    Usage:
        with db_cursor() as cur:
            cur.execute("INSERT INTO users (username) VALUES (%s)", ("john",))
            # Auto-commits on success, rolls back on exception
        
        with db_cursor(commit=False) as cur:
            cur.execute("SELECT * FROM users WHERE id = %s", (1,))
            user = cur.fetchone()  # Returns dict-like Row
    
    Note: Uses %s placeholders for compatibility with db.py (PostgreSQL).
          Internally converts to SQLite's ? placeholders.
    """
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        raw_cursor = conn.cursor()
        cur = SQLiteCursorWrapper(raw_cursor)
        yield cur
        if commit:
            conn.commit()
    except Exception:
        if conn:
            conn.rollback()
        raise
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


# ==================== Table Creation ====================
def create_tables():
    """
    Create all required tables if they don't exist.
    Called once on application startup.
    
    SQLite-specific adaptations:
    - SERIAL PRIMARY KEY -> INTEGER PRIMARY KEY AUTOINCREMENT
    - REFERENCES work but foreign keys need PRAGMA foreign_keys=ON
    """
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        
        # Enable foreign keys
        cur.execute("PRAGMA foreign_keys = ON;")
        
        # Users table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username VARCHAR(80) UNIQUE NOT NULL,
                display_name VARCHAR(120),
                password_hash VARCHAR(256) NOT NULL,
                email VARCHAR(120),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT 1
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)")
        
        # Chat sessions table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS chat_sessions (
                id VARCHAR(36) PRIMARY KEY,
                user_id INTEGER REFERENCES users(id),
                title VARCHAR(255) DEFAULT 'New chat',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                current_topic VARCHAR(255) DEFAULT ''
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON chat_sessions(user_id)")
        
        # Messages table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER REFERENCES users(id) NOT NULL,
                session_id VARCHAR(36) REFERENCES chat_sessions(id),
                role VARCHAR(20) NOT NULL,
                content TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                meta_json TEXT
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_messages_user ON messages(user_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp)")
        
        # Documents table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id VARCHAR(255) UNIQUE NOT NULL,
                filename VARCHAR(255),
                file_type VARCHAR(50),
                file_size INTEGER,
                source VARCHAR(512),
                uploaded_by INTEGER REFERENCES users(id),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_indexed BOOLEAN DEFAULT 0,
                index_status VARCHAR(50) DEFAULT 'pending'
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_documents_doc_id ON documents(doc_id)")
        
        conn.commit()
        cur.close()
    finally:
        conn.close()
    
    print("[DB] Tables created/verified")


# ==================== User Model ====================
class User:
    """
    User class compatible with Flask-Login.
    Wraps database row (sqlite3.Row or dict).
    """
    
    def __init__(self, row):
        """
        Initialize User from a database row.
        
        Args:
            row: sqlite3.Row or dict with user data
        """
        # Handle both sqlite3.Row and dict
        if isinstance(row, sqlite3.Row):
            row = dict(row)
        
        self.id = row.get("id")
        self.username = row.get("username")
        self.display_name = row.get("display_name")
        self.password_hash = row.get("password_hash")
        self.email = row.get("email")
        self.created_at = row.get("created_at")
        self.updated_at = row.get("updated_at")
        # SQLite stores booleans as 0/1
        is_active = row.get("is_active", 1)
        self.is_active = bool(is_active) if is_active is not None else True
        self._row = row
    
    # Flask-Login required properties
    @property
    def is_authenticated(self) -> bool:
        return True
    
    @property
    def is_anonymous(self) -> bool:
        return False
    
    def get_id(self) -> str:
        """Return user ID as string (required by Flask-Login)."""
        return str(self.id)
    
    def check_password(self, password: str) -> bool:
        """Verify password against stored hash."""
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)
    
    def __repr__(self) -> str:
        return f"<User {self.username}>"


# ==================== User Helper Functions ====================
def get_user_by_id(user_id: int) -> Optional[User]:
    """Get user by ID."""
    with db_cursor(commit=False) as cur:
        cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()
        return User(row) if row else None


def get_user_by_username(username: str) -> Optional[User]:
    """Get user by username."""
    with db_cursor(commit=False) as cur:
        cur.execute("SELECT * FROM users WHERE username = %s", (username,))
        row = cur.fetchone()
        return User(row) if row else None


def get_user_by_email(email: str) -> Optional[User]:
    """Get user by email."""
    with db_cursor(commit=False) as cur:
        cur.execute("SELECT * FROM users WHERE email = %s", (email,))
        row = cur.fetchone()
        return User(row) if row else None


def user_exists(username: str) -> bool:
    """Check if username exists."""
    with db_cursor(commit=False) as cur:
        cur.execute("SELECT 1 FROM users WHERE username = %s", (username,))
        return cur.fetchone() is not None


def create_user(
    username: str,
    password: str,
    display_name: Optional[str] = None,
    email: Optional[str] = None,
    is_active: bool = True
) -> Optional[User]:
    """
    Create a new user.
    
    Returns the created User or None if username already exists.
    """
    # Check if user already exists
    if user_exists(username):
        return None
    
    password_hash = generate_password_hash(password)
    now = datetime.now(timezone.utc).isoformat()
    
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO users (username, display_name, password_hash, email, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (username, display_name or username, password_hash, email, 1 if is_active else 0, now, now)
        )
        conn.commit()
        user_id = cur.lastrowid
        cur.close()
    except sqlite3.IntegrityError:
        # Username already exists (unique constraint)
        conn.close()
        return None
    finally:
        conn.close()
    
    # Return the created user
    return get_user_by_id(user_id)


def update_user(user_id: int, **kwargs) -> bool:
    """
    Update user fields.
    
    Usage:
        update_user(1, email="new@email.com", display_name="New Name")
    
    Allowed fields: display_name, email, is_active, password_hash
    """
    allowed_fields = {"display_name", "email", "is_active", "password_hash"}
    updates = {k: v for k, v in kwargs.items() if k in allowed_fields}
    
    if not updates:
        return False
    
    # Convert boolean to int for SQLite
    if "is_active" in updates:
        updates["is_active"] = 1 if updates["is_active"] else 0
    
    # Add updated_at timestamp
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    
    # Build SET clause with ? placeholders
    set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
    values = list(updates.values()) + [user_id]
    
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(f"UPDATE users SET {set_clause} WHERE id = ?", values)
        conn.commit()
        affected = cur.rowcount
        cur.close()
        return affected > 0
    finally:
        conn.close()


# ==================== Seed Demo Users ====================
def seed_demo_users():
    """Create demo users if they don't exist."""
    demo_users = [
        ("demouser", "DemoUser", "DemoPass123!", "demouser@sagealpha.ai"),
        ("devuser", "DevUser", "DevPass123!", "devuser@sagealpha.ai"),
        ("produser", "ProductionUser", "ProdPass123!", "produser@sagealpha.ai"),
    ]
    
    created = 0
    for username, display_name, password, email in demo_users:
        if not user_exists(username):
            user = create_user(
                username=username,
                password=password,
                display_name=display_name,
                email=email
            )
            if user:
                created += 1
    
    if created > 0:
        print(f"[DB] Created {created} demo user(s)")
    else:
        print("[DB] Demo users already exist")


# ==================== Startup / Init ====================
def init_db():
    """
    Initialize database on startup.
    - Tests connection
    - Creates tables
    - Seeds demo users
    """
    print(f"[DB] Using SQLite database at {DB_PATH}")
    
    try:
        # Test connection
        conn = get_db_connection()
        conn.close()
        print("[DB] Connection successful")
        
        # Create tables
        create_tables()
        
        # Seed demo users
        seed_demo_users()
        
    except Exception as e:
        print(f"[DB][ERROR] Database initialization failed: {e}")
        print(f"[DB][ERROR] DB_PATH: {DB_PATH}")
        print(f"[DB][ERROR] IS_PRODUCTION: {IS_PRODUCTION}")
        raise


# ==================== Example Usage ====================
if __name__ == "__main__":
    """
    Example usage and testing:
    
    # Get user by email
    user = get_user_by_email("demouser@sagealpha.ai")
    if user:
        print(f"Found user: {user.username}, email: {user.email}")
    
    # Create new user
    new_user = create_user(
        username="testuser",
        password="TestPass123!",
        display_name="Test User",
        email="test@example.com"
    )
    
    # Query with raw cursor (using %s placeholders)
    with db_cursor(commit=False) as cur:
        cur.execute("SELECT id, username, email FROM users WHERE id = %s", (1,))
        row = cur.fetchone()
        if row:
            print(f"User: {row['id']}, {row['username']}, {row['email']}")
    
    # Insert with auto-commit
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO messages (user_id, role, content) VALUES (%s, %s, %s)",
            (1, "user", "Hello, SageAlpha!")
        )
    """
    print("Testing SQLite database connection...")
    print(f"IS_PRODUCTION: {IS_PRODUCTION}")
    print(f"DB_PATH: {DB_PATH}")
    print()
    
    init_db()
    
    print("\nListing users:")
    with db_cursor(commit=False) as cur:
        cur.execute("SELECT id, username, email FROM users")
        for row in cur.fetchall():
            # sqlite3.Row supports dict-like access
            print(f"  {row['id']}: {row['username']} <{row['email']}>")
    
    print("\nTesting %s placeholder conversion:")
    with db_cursor(commit=False) as cur:
        cur.execute("SELECT * FROM users WHERE username = %s", ("demouser",))
        user_row = cur.fetchone()
        if user_row:
            user = User(user_row)
            print(f"  Found: {user}")
            print(f"  Password check (correct): {user.check_password('DemoPass123!')}")
            print(f"  Password check (wrong): {user.check_password('wrongpass')}")

