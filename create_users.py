"""
SageAlpha.ai User Creation Script
Creates/updates demo users using SQLite backend
"""

import os
import sys

from werkzeug.security import generate_password_hash

# Add the project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db_sqlite import (
    create_tables,
    create_user,
    db_cursor,
    get_user_by_username,
    init_db,
    seed_demo_users,
    update_user,
    user_exists,
)


def create_users():
    """Create or update demo users using SQLite."""
    print("[create_users] Initializing database...")
    
    # Initialize database and create tables
    init_db()
    
    print("\n[create_users] Demo accounts available:")
    print("  - demouser / Demouser")
    print("  - devuser / Devuser")
    print("  - produser / Produser")


def reset_user_password(username: str, new_password: str):
    """Reset a user's password."""
    user = get_user_by_username(username)
    if user:
        new_hash = generate_password_hash(new_password)
        if update_user(user.id, password_hash=new_hash):
            print(f"Password reset for user: {username}")
        else:
            print(f"Failed to update password for: {username}")
    else:
        print(f"User not found: {username}")


def list_users():
    """List all users in the database."""
    print("\n[list_users] Current users:")
    with db_cursor(commit=False) as cur:
        cur.execute("SELECT id, username, email, is_active, created_at FROM users ORDER BY id")
        users = cur.fetchall()
        if not users:
            print("  No users found")
        for u in users:
            status = "active" if u["is_active"] else "inactive"
            print(f"  {u['id']}: {u['username']} <{u['email']}> [{status}]")


def add_user(username: str, password: str, email: str = None):
    """Add a new user."""
    if user_exists(username):
        print(f"User already exists: {username}")
        return
    
    user = create_user(
        username=username,
        password=password,
        display_name=username,
        email=email or f"{username}@sagealpha.ai"
    )
    
    if user:
        print(f"Created user: {username}")
    else:
        print(f"Failed to create user: {username}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        
        if cmd == "--reset" and len(sys.argv) >= 4:
            # Usage: python create_users.py --reset username newpassword
            reset_user_password(sys.argv[2], sys.argv[3])
        
        elif cmd == "--list":
            # Usage: python create_users.py --list
            list_users()
        
        elif cmd == "--add" and len(sys.argv) >= 4:
            # Usage: python create_users.py --add username password [email]
            email = sys.argv[4] if len(sys.argv) > 4 else None
            add_user(sys.argv[2], sys.argv[3], email)
        
        else:
            print("Usage:")
            print("  python create_users.py                  # Create demo users")
            print("  python create_users.py --list           # List all users")
            print("  python create_users.py --reset <user> <pass>   # Reset password")
            print("  python create_users.py --add <user> <pass> [email]  # Add user")
    else:
        create_users()
