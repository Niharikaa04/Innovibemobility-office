"""CSV helpers shared by exports. Cells starting with = + - @ (or tab/CR) are prefixed with an apostrophe so spreadsheet
software cannot run them as formulas (CSV injection)."""
import csv, io
from fastapi import Response

def safe_cell(v):
    if v is None: return ""
    s = v.isoformat() if hasattr(v, "isoformat") else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s

def csv_response(filename: str, header: list, rows: list) -> Response:
    buf = io.StringIO(); w = csv.writer(buf, lineterminator="\r\n"); w.writerow(header)
    for r in rows: w.writerow([safe_cell(c) for c in r])
    return Response("\ufeff" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"})
