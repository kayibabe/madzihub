import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
from app.database import SessionLocal, FiscalYear
db = SessionLocal()
rows = db.query(FiscalYear).order_by(FiscalYear.year).all()
print(f"Total fiscal years: {len(rows)}")
for r in rows:
    print(f"  {r.label}  status={r.status}")
db.close()
