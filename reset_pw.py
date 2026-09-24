import sys, os
sys.path.insert(0, r"D:\WebApps\opsapp")
os.chdir(r"D:\WebApps\opsapp")
import bcrypt as _bcrypt
from app.database import SessionLocal, User

new_pw = "Admin2026!"
hashed = _bcrypt.hashpw(new_pw.encode(), _bcrypt.gensalt()).decode()

db = SessionLocal()
u = db.query(User).filter(User.username == "Cromwell").first()
if u:
    u.password_hash = hashed
    db.commit()
    print("Done — password for", u.username, "reset to:", new_pw)
else:
    print("User 'Cromwell' not found. All users:")
    for usr in db.query(User).all():
        print(" ", usr.username, usr.role)
db.close()
