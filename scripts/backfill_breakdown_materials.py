from __future__ import annotations

import io
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.excel_parser import ExcelParser

DB_PATH = ROOT / 'data' / 'srwb.db'
RAW_XLSX = ROOT / 'uploads' / 'RawData.xlsx'
BREAKDOWN_FIELDS = [
    'pipe_pvc', 'pipe_gi', 'pipe_di', 'pipe_hdpe_ac',
    'pvc_20mm', 'pvc_25mm', 'pvc_32mm', 'pvc_40mm', 'pvc_50mm', 'pvc_63mm',
    'pvc_75mm', 'pvc_90mm', 'pvc_110mm', 'pvc_160mm', 'pvc_200mm', 'pvc_250mm', 'pvc_315mm',
]


def main() -> None:
    if not DB_PATH.exists():
        raise FileNotFoundError(f'Database not found: {DB_PATH}')
    if not RAW_XLSX.exists():
        raise FileNotFoundError(f'RawData workbook not found: {RAW_XLSX}')

    conn = sqlite3.connect(DB_PATH)
    try:
        with RAW_XLSX.open('rb') as fh:
            buf = io.BytesIO(fh.read())
        result = ExcelParser().parse(buf, conn)

        updated = 0
        missing = 0
        sql = f"""
            UPDATE records
               SET {', '.join(f'{field}=?' for field in BREAKDOWN_FIELDS)}
             WHERE zone=? AND scheme=? AND year=? AND month_no=?
        """
        for row in result.importable_rows:
            metrics = row.metrics
            values = [metrics.get(field, 0) or 0 for field in BREAKDOWN_FIELDS]
            cur = conn.execute(sql, values + [row.zone, row.scheme, row.year, row.month])
            if cur.rowcount:
                updated += cur.rowcount
            else:
                missing += 1

        conn.commit()

        sums = {
            field: conn.execute(f'SELECT COALESCE(SUM({field}),0) FROM records').fetchone()[0]
            for field in BREAKDOWN_FIELDS[:4]
        }
        print('Backfill complete')
        print(f'Updated rows: {updated}')
        print(f'Rows missing in DB: {missing}')
        for field, value in sums.items():
            print(f'{field}: {value}')
    finally:
        conn.close()


if __name__ == '__main__':
    main()
