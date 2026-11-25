"""Create or promote an administrator without exposing an admin signup route."""
from getpass import getpass
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from werkzeug.security import generate_password_hash
from backend.app import app
from backend.database import get_db

email = input("Admin email: ").strip().lower()
name = input("Admin display name: ").strip()
password = getpass("Admin password (12+ characters): ")
if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
    raise SystemExit("Enter a valid email address.")
if len(name) < 2 or not 12 <= len(password) <= 128:
    raise SystemExit("Name must have at least 2 characters and password must have 12–128 characters.")

with app.app_context():
    database = get_db()
    existing = database.execute("SELECT id FROM users WHERE email=? COLLATE NOCASE", (email,)).fetchone()
    if existing:
        database.execute("UPDATE users SET role='admin',name=?,password_hash=? WHERE id=?", (name, generate_password_hash(password, method="scrypt"), existing["id"]))
    else:
        database.execute("INSERT INTO users(id,email,name,password_hash,role,created_at) VALUES(?,?,?,?,?,?)", (str(uuid.uuid4()), email, name, generate_password_hash(password, method="scrypt"), "admin", datetime.now(timezone.utc).isoformat()))
    database.commit()
    database.close()
print("Administrator account is ready. Sign in through the Finwell login page.")
