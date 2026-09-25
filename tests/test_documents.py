"""Document control: evidence pinned to versions, controlled documents, upload checks, search, backup."""
from __future__ import annotations

import io
import unittest
import zipfile
from datetime import date
from pathlib import Path

from sqlalchemy import text

from tests._access import add_user
from tests._fixture import AppFixture


def docx(body: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", f"<w:document><w:body><w:p><w:r><w:t>{body}</w:t></w:r></w:p></w:body></w:document>")
    return buf.getvalue()


def broken_xlsx() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("xl/workbook.xml", "not really a workbook")
    return buf.getvalue()


class DocFixture(AppFixture):
    def setUp(self):
        super().setUp()
        self.dc = add_user(self.database, self.auth, "dora", "user", {"org": "viewer"}, functions=("document_controller",))
        self.types = {t["code"]: t["id"] for t in self.get("/api/documents/types", self.nick)}

    def upload(self, url, h, name, data, code=201, **form):
        r = self.c.post(url, headers=h, files={"file": (name, data)}, data=form)
        self.assertEqual(r.status_code, code, r.text)
        return r.json()

    def action(self, unit="north", h=None):
        return self.post("/api/platform/actions", h or self.nora,
                         {"title": "Repair main", "owner": "nick", "org_unit_code": unit}, 201)


class EvidenceTests(DocFixture):
    def test_evidence_is_pinned_to_the_exact_version_and_replacements_keep_history(self):
        a = self.action()
        first = self.upload("/api/documents/evidence", self.nick, "repair-log.txt", b"Valve 12 replaced on site.",
                            entity_type="action", entity_id=str(a["id"]))
        doc_id = first["id"]
        self.assertEqual((first["attached_version"], first["org_unit_code"], first["type"]["code"]), (1, "north", "evidence"))
        second = self.upload("/api/documents/evidence", self.nick, "repair-log.txt", b"Valve 12 and 13 replaced.",
                             entity_type="action", entity_id=str(a["id"]), document_id=str(doc_id),
                             note="Second valve added")
        self.assertEqual([v["version"] for v in second["versions"]], [2, 1])
        links = self.get(f"/api/platform/links?type=action&id={a['id']}", self.nick)["links"]
        pins = sorted(l["to_version"] for l in links if l["relation"] == "evidence")
        self.assertEqual(pins, [1, 2])
        r1 = self.c.get(f"/api/documents/{doc_id}/download?version=1", headers=self.nora)
        self.assertEqual(r1.content, b"Valve 12 replaced on site.")
        self.assertEqual(r1.headers["x-document-sha256"], second["versions"][1]["sha256"])
        self.assertIn("attachment", r1.headers["content-disposition"])
        # Region scope: South cannot see the evidence, its versions or the download.
        self.assertEqual(self.status("get", f"/api/documents/{doc_id}", self.sam), 404)
        self.assertEqual(self.c.get(f"/api/documents/{doc_id}/download", headers=self.sam).status_code, 404)
        # And cannot attach evidence to a North record.
        self.upload("/api/documents/evidence", self.sam, "x.txt", b"hi", code=404, entity_type="action",
                    entity_id=str(a["id"]))
        with self.database.engine.connect() as conn:
            with self.assertRaises(Exception):
                conn.execute(text("UPDATE document_versions SET sha256 = 'x'"))

    def test_spoofed_and_disallowed_uploads_are_refused(self):
        a = self.action()
        url = "/api/documents/evidence"
        common = {"entity_type": "action", "entity_id": str(a["id"])}
        for name, data, why in (("report.pdf", b"just text, not a PDF", "does not match"),
                                ("notes.txt", b"MZ\x90\x00 executable", "Executable"),
                                ("page.txt", b"<!DOCTYPE html><script>alert(1)</script>", "does not match"),
                                ("tool.exe", b"MZ\x90", "not accepted"),
                                ("sheet.xlsx", b"PK\x03\x04garbage", "does not match"),
                                ("empty.txt", b"", "empty")):
            r = self.c.post(url, headers=self.nick, files={"file": (name, data)}, data=common)
            self.assertEqual(r.status_code, 422, name)
            self.assertIn(why, r.json()["detail"], name)

    def test_evidence_satisfies_the_progress_update_evidence_check(self):
        pid = self.post("/api/strategy/plans", self.planner, {"code": "E", "title": "E", "start_fy": 2027, "end_fy": 2028}, 201)["id"]
        self.post(f"/api/strategy/plans/{pid}/indicators", self.planner, {
            "code": "EV", "name": "Evidence needed", "frequency": "quarter", "evidence_required": True,
            "reporting_units": ["north"]}, 201)
        self.post(f"/api/strategy/plans/{pid}/transition", self.planner, {"name": "activate"})
        q = next(p for p in self.get("/api/platform/periods?period_type=quarter", self.planner)
                 if p["start_date"] <= date.today().isoformat() <= p["end_date"])
        c = self.post(f"/api/strategy/plans/{pid}/cycles", self.planner, {"period_id": q["id"]}, 201)
        self.post(f"/api/strategy/cycles/{c['id']}/generate", self.planner)
        self.post(f"/api/strategy/cycles/{c['id']}/transition", self.planner, {"name": "open"})
        aid = self.get(f"/api/strategy/assignments?cycle_id={c['id']}&queue=all", self.nick)[0]["id"]
        self.upload("/api/documents/evidence", self.nick, "count.csv", b"meter,reading\n1,40\n",
                    entity_type="cycle_assignment", entity_id=str(aid))
        out = self.post(f"/api/strategy/assignments/{aid}/submit", self.nick, {"value": 40}, 201)
        dqa = {d["check"]: d["result"] for d in out["revisions"][0]["dqa"]}
        self.assertEqual(dqa["evidence"], "pass")


class ControlledDocumentTests(DocFixture):
    def test_policy_lifecycle_with_revision_and_supersession(self):
        pol = self.post("/api/documents", self.dc, {"type_id": self.types["policy"], "title": "Water quality policy",
                                                    "org_unit_code": "org", "owner": "planner", "approver": "nate",
                                                    "tags": ["Quality", "Safety"]}, 201)
        self.assertEqual((pol["number"], pol["revision"], pol["status"], pol["tags"]), ("POL-0001", 1, "draft", ["quality", "safety"]))
        url = f"/api/documents/{pol['id']}"
        self.assertEqual(self.status("post", f"{url}/transition", self.nate, {"name": "approve"}), 422)   # no file
        self.upload(f"{url}/versions", self.planner, "wq.pdf", b"%PDF-1.4 not really parsed", code=201)
        d = self.upload(f"{url}/versions", self.planner, "wq.docx", docx("Chlorine residual shall be monitored daily."))
        self.assertEqual(d["versions"][0]["extraction_status"], "ok")
        self.assertEqual(d["versions"][1]["extraction_status"], "failed")     # recorded, file kept
        self.assertEqual(self.status("post", f"{url}/transition", self.planner, {"name": "approve"}), 403)  # owner
        self.assertEqual(self.status("post", f"{url}/transition", self.nora, {"name": "approve"}), 404)     # cannot see it
        self.assertEqual(self.status("post", f"{url}/transition", self.vic, {"name": "approve"}), 403)      # read-only
        approved = self.post(f"{url}/transition", self.nate, {"name": "approve"})
        self.assertEqual((approved["status"], approved["approved_version"]), ("approved", 2))
        self.upload(f"{url}/versions", self.planner, "late.docx", docx("x"), code=409)   # frozen after approval
        eff = self.post(f"{url}/transition", self.planner, {"name": "make_effective"})
        self.assertEqual(eff["status"], "effective")
        self.assertEqual(eff["review_date"][:4], str(date.fromisoformat(eff["effective_date"]).year + 3))

        rev = self.post(f"{url}/revise", self.planner, None, 201)
        self.assertEqual((rev["number"], rev["revision"], rev["status"]), ("POL-0001", 2, "draft"))
        self.assertEqual(self.status("post", f"{url}/revise", self.planner), 409)   # one revision at a time
        self.upload(f"/api/documents/{rev['id']}/versions", self.planner, "wq2.docx", docx("Monitored twice daily."))
        self.post(f"/api/documents/{rev['id']}/transition", self.dc, {"name": "approve"})
        self.post(f"/api/documents/{rev['id']}/transition", self.planner, {"name": "make_effective"})
        self.assertEqual(self.get(url, self.planner)["status"], "superseded")
        master = self.get("/api/documents?controlled=true", self.vic)
        self.assertEqual([(m["number"], m["revision"], m["status"]) for m in master],
                         [("POL-0001", 2, "effective"), ("POL-0001", 1, "superseded")])
        self.assertEqual(self.status("post", f"/api/documents/{rev['id']}/transition", self.planner, {"name": "withdraw"}), 422)

    def test_classification_limits_records_search_and_snippets(self):
        mk = lambda title, cls, unit, body: self.upload(
            f"/api/documents/{self.post('/api/documents', self.dc, {'type_id': self.types['evidence'], 'title': title, 'org_unit_code': unit, 'owner': 'nate', 'classification': cls}, 201)['id']}/versions",
            self.dc, f"{title}.txt", body.encode())
        restricted = mk("Tariff negotiation", "restricted", "north", "zebracrossing tariff position")
        confidential = mk("Staff grievance summary", "confidential", "north", "zebracrossing grievance")
        internal = mk("Network map notes", "internal", "north", "zebracrossing pipes")
        south = mk("South pump log", "internal", "south", "zebracrossing pump")
        seen = lambda h: {r["title"] for r in self.get("/api/documents/search?q=zebracrossing", h)}
        self.assertEqual(seen(self.nick), {"Network map notes"})                       # contributor
        self.assertEqual(seen(self.nora), {"Network map notes", "Staff grievance summary"})   # reviewer
        # Nate is the named owner of all four, which lets him see even the South one.
        self.assertEqual(seen(self.nate), {"Network map notes", "Staff grievance summary", "Tariff negotiation",
                                           "South pump log"})
        self.assertEqual(seen(self.sam), {"South pump log"})
        self.assertEqual(self.status("get", f"/api/documents/{restricted['id']}", self.nora), 404)
        hit = self.get("/api/documents/search?q=zebracrossing", self.nick)[0]
        self.assertIn("[zebracrossing]", hit["snippet"])
        self.assertTrue(confidential and internal and south)
        self.assertEqual(self.status("get", "/api/documents/search?q=z", self.nick), 422)

    def test_tampered_file_is_refused_on_download(self):
        a = self.action()
        d = self.upload("/api/documents/evidence", self.nick, "log.txt", b"original", entity_type="action", entity_id=str(a["id"]))
        from app.modules.documents.models import DocumentVersion
        from app.platform import filestore
        db = self.db()
        try:
            v = db.query(DocumentVersion).filter_by(document_id=d["id"]).one()
            p = Path(filestore.root()) / v.storage_name[:2] / v.storage_name[2:4] / v.storage_name
        finally:
            db.close()
        p.chmod(0o666)
        p.write_bytes(b"forged")
        r = self.c.get(f"/api/documents/{d['id']}/download", headers=self.nick)
        self.assertEqual(r.status_code, 409)


class BackupTests(DocFixture):
    def test_backup_verify_and_restore_round_trip(self):
        a = self.action()
        self.upload("/api/documents/evidence", self.nick, "log.txt", b"keep me safe", entity_type="action", entity_id=str(a["id"]))
        from app.platform import backup
        archive = backup.create(self.tmp / "bk")
        manifest = backup.verify(archive)
        self.assertEqual(len(manifest["files"]), 1)
        self.assertIsNotNone(manifest["revision"])
        target_db, target_files = self.tmp / "restored" / "r.db", self.tmp / "restored" / "files"
        backup.restore(archive, target_db, target_files)
        import sqlite3
        con = sqlite3.connect(target_db)
        try:
            self.assertEqual(con.execute("SELECT title FROM actions").fetchone()[0], "Repair main")
        finally:
            con.close()
        restored = [p.read_bytes() for p in target_files.rglob("*") if p.is_file()]
        self.assertEqual(restored, [b"keep me safe"])
        with self.assertRaises(backup.BackupError):
            backup.restore(archive, target_db, self.tmp / "other")     # never overwrites
        # A corrupted archive fails verification.
        bad = self.tmp / "bad.zip"
        with zipfile.ZipFile(archive) as src, zipfile.ZipFile(bad, "w") as dst:
            for item in src.infolist():
                data = src.read(item.filename)
                dst.writestr(item, b"tampered" if item.filename.startswith("files/") else data)
        with self.assertRaises(backup.BackupError):
            backup.verify(bad)


if __name__ == "__main__":
    unittest.main()
