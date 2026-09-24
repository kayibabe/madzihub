"""
Run this from inside the srwb_package folder:
  python reset_password.py
"""
import sys, os
sys.path.insert(0, '.')

from app.database import SessionLocal, User, Base, engine
from app.auth import hash_password, verify_password

# Create tables if they don't exist yet
Base.metadata.create_all(bind=engine)

db = SessionLocal()

admin = db.query(User).filter(User.username == "admin").first()

if admin:
    admin.password_hash = hash_password("Admin123")
    db.commit()
    ok = verify_password("Admin123", admin.password_hash)
    print(f"✓ Password reset successful")
else:
    # No admin exists — create one
    from app.database import User as UserModel
    new_admin = UserModel(
        username="admin",
        password_hash=hash_password("Admin123"),
        role="admin",
        is_active=True,
        created_by="reset_script",
    )
    db.add(new_admin)
    db.commit()
    print(f"✓ Admin account created")

print(f"\n  Username: admin")
print(f"  Password: Admin123")
print(f"\nRestart uvicorn and log in.")
db.close()
