"""
SageAlpha.ai v3.0 - PostgreSQL Database Layer
Pure psycopg2 implementation for Azure PostgreSQL (no SQLAlchemy)
"""

import os
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Optional

import psycopg2
from psycopg2.extras import RealDictCursor
from werkzeug.security import check_password_hash, generate_password_hash

# ==================== Database Configuration ====================
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# Parse connection string or use components
def get_connection_params() -> dict:
    """Parse DATABASE_URL or build from components."""
    url = DATABASE_URL
    
    if not url:
        # Fallback to individual env vars (Azure style)
        return {
            "host": os.environ.get("PGHOST", "localhost"),
            "port": int(os.environ.get("PGPORT", 5432)),
            "database": os.environ.get("PGDATABASE", "postgres"),
            "user": os.environ.get("PGUSER", "postgres"),
            "password": os.environ.get("PGPASSWORD", ""),
            "sslmode": os.environ.get("PGSSLMODE", "require"),
        }
    
    # Parse DATABASE_URL format: postgresql://user:pass@host:port/dbname
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    
    # For psycopg2, we can pass the URL directly
    return {"dsn": url}


def get_db_connection():
    """
    Get a new database connection.
    Returns a psycopg2 connection with RealDictCursor.
    
    Usage:
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM users")
                rows = cur.fetchall()
        finally:
            conn.close()
    """
    params = get_connection_params()
    
    if "dsn" in params:
        conn = psycopg2.connect(params["dsn"], cursor_factory=RealDictCursor)
    else:
        conn = psycopg2.connect(
            cursor_factory=RealDictCursor,
            **params
        )
    
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
            user = cur.fetchone()  # Returns dict like {'id': 1, 'username': 'john'}
    """
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        yield cur
        if commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


# ==================== Table Creation ====================
def create_tables():
    """
    Create all required tables if they don't exist.
    Called once on application startup.
    """
    with db_cursor() as cur:
        # Users table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(80) UNIQUE NOT NULL,
                display_name VARCHAR(120),
                password_hash VARCHAR(256) NOT NULL,
                email VARCHAR(120),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT TRUE
            );
            CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
            CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
        """)
        
        # Chat sessions table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS chat_sessions (
                id VARCHAR(36) PRIMARY KEY,
                user_id INTEGER REFERENCES users(id),
                title VARCHAR(255) DEFAULT 'New chat',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                current_topic VARCHAR(255) DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_sessions_user ON chat_sessions(user_id);
        """)
        
        # Messages table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) NOT NULL,
                session_id VARCHAR(36) REFERENCES chat_sessions(id),
                role VARCHAR(20) NOT NULL,
                content TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                meta_json TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_messages_user ON messages(user_id);
            CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
            CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp);
        """)
        
        # Documents table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id SERIAL PRIMARY KEY,
                doc_id VARCHAR(255) UNIQUE NOT NULL,
                filename VARCHAR(255),
                file_type VARCHAR(50),
                file_size INTEGER,
                source VARCHAR(512),
                uploaded_by INTEGER REFERENCES users(id),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_indexed BOOLEAN DEFAULT FALSE,
                index_status VARCHAR(50) DEFAULT 'pending'
            );
            CREATE INDEX IF NOT EXISTS idx_documents_doc_id ON documents(doc_id);
        """)
    
    print("[DB] Tables created/verified")


# ==================== User Model Functions ====================
class User:
    """
    User class compatible with Flask-Login.
    Wraps database row dictionary.
    """
    def __init__(self, row: dict):
        self.id = row.get("id")
        self.username = row.get("username")
        self.display_name = row.get("display_name")
        self.password_hash = row.get("password_hash")
        self.email = row.get("email")
        self.created_at = row.get("created_at")
        self.updated_at = row.get("updated_at")
        self.is_active = row.get("is_active", True)
        self._row = row
    
    # Flask-Login required properties
    @property
    def is_authenticated(self) -> bool:
        return True
    
    @property
    def is_anonymous(self) -> bool:
        return False
    
    def get_id(self) -> str:
        return str(self.id)
    
    def check_password(self, password: str) -> bool:
        """Verify password against stored hash."""
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)
    
    def __repr__(self) -> str:
        return f"<User {self.username}>"


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
    password_hash = generate_password_hash(password)
    
    with db_cursor() as cur:
        try:
            cur.execute("""
                INSERT INTO users (username, display_name, password_hash, email, is_active)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING *
            """, (username, display_name or username, password_hash, email, is_active))
            row = cur.fetchone()
            return User(row) if row else None
        except psycopg2.errors.UniqueViolation:
            return None  # Username already exists


def update_user(user_id: int, **kwargs) -> bool:
    """
    Update user fields.
    
    Usage:
        update_user(1, email="new@email.com", display_name="New Name")
    """
    allowed_fields = {"display_name", "email", "is_active", "password_hash"}
    updates = {k: v for k, v in kwargs.items() if k in allowed_fields}
    
    if not updates:
        return False
    
    updates["updated_at"] = datetime.now(timezone.utc)
    
    set_clause = ", ".join(f"{k} = %s" for k in updates.keys())
    values = list(updates.values()) + [user_id]
    
    with db_cursor() as cur:
        cur.execute(f"UPDATE users SET {set_clause} WHERE id = %s", values)
        return cur.rowcount > 0


def user_exists(username: str) -> bool:
    """Check if username exists."""
    with db_cursor(commit=False) as cur:
        cur.execute("SELECT 1 FROM users WHERE username = %s", (username,))
        return cur.fetchone() is not None


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


# ==================== Startup Check ====================
def init_db():
    """Initialize database on startup."""
    db_url = os.environ.get("DATABASE_URL", "")
    
    if "postgres" in db_url.lower():
        print("[DB] Connected to Azure PostgreSQL")
    else:
        print("[DB] Using PostgreSQL")
    
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
    
    # Query with raw cursor
    with db_cursor(commit=False) as cur:
        cur.execute("SELECT id, username, email FROM users LIMIT 10")
        for row in cur.fetchall():
            print(f"User {row['id']}: {row['username']} ({row['email']})")
    
    # Insert with auto-commit
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO messages (user_id, role, content) VALUES (%s, %s, %s)",
            (1, "user", "Hello, SageAlpha!")
        )
    """
    print("Testing database connection...")
    init_db()
    
    print("\nListing users:")
    with db_cursor(commit=False) as cur:
        cur.execute("SELECT id, username, email FROM users")
        for row in cur.fetchall():
            print(f"  {row['id']}: {row['username']} <{row['email']}>")

