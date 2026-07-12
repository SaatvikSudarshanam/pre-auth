"""Quick end-to-end smoke test using FastAPI TestClient (no network / no LLM)."""
from fastapi.testclient import TestClient

from database import Base, SessionLocal, engine
from main import app
from seed import seed_if_empty

# TestClient does not fire the startup lifespan, so init the DB explicitly here.
# (Under real uvicorn, main.on_startup handles this.)
Base.metadata.create_all(bind=engine)
_db = SessionLocal()
seed_if_empty(_db)
_db.close()

c = TestClient(app)


def ok(label, cond):
    print(("PASS" if cond else "FAIL"), "-", label)
    assert cond, label


def pdf_bytes(lines):
    """Minimal single-page PDF with extractable text (for fraud/mismatch test)."""
    ops = "BT /F1 12 Tf 72 720 Td 15 TL\n"
    for ln in lines:
        safe = ln.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        ops += f"({safe}) Tj T*\n"
    ops += "ET"
    content = ops.encode("latin-1", "replace")
    objs = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>",
        b"<</Length " + str(len(content)).encode() + b">>\nstream\n" + content + b"\nendstream",
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    out = b"%PDF-1.4\n"
    offs = []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    n = len(objs) + 1
    out += f"xref\n0 {n}\n".encode() + b"0000000000 65535 f \n"
    for off in offs:
        out += f"{off:010d} 00000 n \n".encode()
    out += b"trailer\n<</Size " + str(n).encode() + b"/Root 1 0 R>>\nstartxref\n" + str(xref).encode() + b"\n%%EOF"
    return out


# health + startup seed
r = c.get("/api/health")
ok("health", r.status_code == 200)

# admin login with env creds
r = c.post("/api/auth/admin/login", json={"username": "admin", "password": "admin@2026"})
ok("admin login", r.status_code == 200 and r.json()["role"] == "admin")
admin_tok = r.json()["access_token"]
admin_h = {"Authorization": f"Bearer {admin_tok}"}

import time as _time


def ai_review(cid):
    """POST ai-review, retrying on transient non-200 (Groq rate limits under burst)."""
    resp = None
    for attempt in range(5):
        resp = c.post(f"/api/admin/claims/{cid}/ai-review", headers=admin_h)
        if resp.status_code == 200:
            return resp
        _time.sleep(4)
    return resp

# wrong admin creds rejected
ok("admin bad creds", c.post("/api/auth/admin/login",
   json={"username": "admin", "password": "nope"}).status_code == 401)

# admin queue has 3 seeded claims
r = c.get("/api/admin/claims", headers=admin_h)
ok("admin queue seeded", r.status_code == 200 and len(r.json()) == 3)

# stats present
r = c.get("/api/admin/stats", headers=admin_h)
ok("admin stats", r.status_code == 200 and "pending" in r.json())

# customer signup
import uuid
email = f"test-{uuid.uuid4().hex[:6]}@example.com"
r = c.post("/api/auth/signup", json={"email": email, "password": "Passw0rd!"})
ok("signup", r.status_code == 200 and r.json()["profile_complete"] is False)
cust_tok = r.json()["access_token"]
cust_h = {"Authorization": f"Bearer {cust_tok}"}

# customer token rejected on admin route
ok("customer blocked from admin", c.get("/api/admin/claims", headers=cust_h).status_code == 403)

# admin token rejected on customer route (role mismatch)
ok("admin blocked from customer", c.get("/api/me", headers=admin_h).status_code == 403)

# list plans, complete profile
r = c.get("/api/plans", headers=cust_h)
ok("plans list", r.status_code == 200 and len(r.json()) == 3)
plan_id = r.json()[1]["id"]  # Silver PPO
r = c.post("/api/me/profile", headers=cust_h,
           json={"full_name": "Test User", "dob": "1992-01-01", "plan_id": plan_id})
ok("profile complete + member id", r.status_code == 200 and r.json()["member_id"].startswith("MEM-2026-"))

# create draft claim (procedure needs prescription, itemized_bill, id_proof)
r = c.post("/api/claims", headers=cust_h, json={
    "claim_type": "procedure", "provider_name": "Test Clinic",
    "diagnosis_text": "test", "date_of_service": "2026-07-01", "amount": 20000})
ok("create claim", r.status_code == 200)
claim_id = r.json()["id"]
ok("required docs computed", set(r.json()["required_documents"]) ==
   {"prescription", "itemized_bill", "id_proof"})

# submit blocked with missing docs
r = c.post(f"/api/claims/{claim_id}/submit", headers=cust_h)
ok("submit blocked when incomplete", r.status_code == 400 and "missing" in str(r.json()))

# upload the 3 required docs (tiny PNG bytes)
png = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080600000"
    "01f15c4890000000d49444154789c6360000002000100ffff03000006"
    "0005570c9d0000000049454e44ae426082")
for dt in ["prescription", "itemized_bill", "id_proof"]:
    r = c.post(f"/api/claims/{claim_id}/documents", headers=cust_h,
               data={"doc_type": dt}, files={"file": (f"{dt}.png", png, "image/png")})
    ok(f"upload {dt}", r.status_code == 200)

# now submit succeeds
r = c.post(f"/api/claims/{claim_id}/submit", headers=cust_h)
ok("submit succeeds when complete", r.status_code == 200 and r.json()["status"] == "submitted")

# admin sees the new claim; run detail
r = c.get(f"/api/admin/claims/{claim_id}", headers=admin_h)
ok("admin claim detail", r.status_code == 200 and r.json()["plan"]["name"] == "Silver PPO")

# AI review: runs the 6-agent pipeline live if GROQ_API_KEY is set, else 502.
import os


def llm_unavailable(resp):
    """True if a 502 is due to Groq rate-limit / daily-quota (not a code bug)."""
    if resp is None or resp.status_code != 502:
        return False
    txt = str(resp.json()).lower()
    return any(k in txt for k in ("rate limit", "429", "tpd", "unavailable", "quota"))


LLM_LIVE = False
if os.getenv("GROQ_API_KEY"):
    r = ai_review(claim_id)
    if llm_unavailable(r):
        print("SKIP - live AI review (Groq quota/rate limit hit — not a code error)")
    else:
        body = r.json()
        LLM_LIVE = True
        ok("ai-review runs (200)", r.status_code == 200)
        ok("ai-review has verdict", body.get("verdict") in ("approve", "reject", "needs_info"))
        ok("ai-review ran 6 agents", len(body.get("agents", [])) == 6)
        ok("integrity agent present", any(a["key"] == "document_integrity" for a in body.get("agents", [])))
        ok("integrity summary present", isinstance(body.get("integrity"), dict))
        ok("ai-review final_score present", isinstance(body.get("final_score"), int))
        print("     verdict:", body.get("verdict"), "| final_score:", body.get("final_score"),
              "| integrity:", (body.get("integrity") or {}).get("verdict"),
              "| identity_match:", (body.get("integrity") or {}).get("identity_match"))
        print("     agents:", [a["key"] for a in body.get("agents", [])])
else:
    r = c.post(f"/api/admin/claims/{claim_id}/ai-review", headers=admin_h)
    ok("ai-review returns 502 without key (wired, isolated)", r.status_code == 502)

# admin decision -> more info; customer sees message + status
r = c.post(f"/api/admin/claims/{claim_id}/decision", headers=admin_h, json={
    "action": "requested_info", "customer_message": "Please add a clearer bill.",
    "agreed_with_ai": None})
ok("admin decision", r.status_code == 200 and r.json()["status"] == "more_info_needed")
r = c.get(f"/api/claims/{claim_id}", headers=cust_h)
ok("customer sees decision", r.json()["status"] == "more_info_needed"
   and "clearer bill" in (r.json()["customer_message"] or ""))

# more-info round trip: uploading a doc flips back to under_review
r = c.post(f"/api/claims/{claim_id}/documents", headers=cust_h,
           data={"doc_type": "itemized_bill"},
           files={"file": ("bill2.png", png, "image/png")})
ok("upload flips to under_review", r.json()["status"] == "under_review")

# ---- Deterministic OCR + identity gate (NO Groq needed — always runs) ----------
# Proves images are read via OCR and that a name mismatch is caught, independent
# of the LLM. This is the core anti-fraud guarantee.
import io as _io
from PIL import Image, ImageDraw, ImageFont
from models import Claim
from services.integrity import check_identity


def _bill_png(patient_name):
    img = Image.new("RGB", (760, 300), "white")
    d = ImageDraw.Draw(img)
    try:
        f = ImageFont.truetype("arial.ttf", 26)
    except Exception:
        f = ImageFont.load_default()
    d.text((30, 30), "City Hospital - Itemized Bill", fill="black", font=f)
    d.text((30, 90), f"Patient: {patient_name}", fill="black", font=f)
    d.text((30, 150), "TOTAL ..... 2,000", fill="black", font=f)
    b = _io.BytesIO(); img.save(b, "PNG"); return b.getvalue()


def _image_claim(full_name, doc_name):
    em = f"ocr-{uuid.uuid4().hex[:6]}@example.com"
    tok = c.post("/api/auth/signup", json={"email": em, "password": "Passw0rd!"}).json()["access_token"]
    hh = {"Authorization": f"Bearer {tok}"}
    c.post("/api/me/profile", headers=hh,
           json={"full_name": full_name, "dob": "1990-01-01", "plan_id": plan_id})
    cid = c.post("/api/claims", headers=hh, json={
        "claim_type": "pharmacy", "provider_name": "P", "diagnosis_text": "m",
        "date_of_service": "2026-07-01", "amount": 2000}).json()["id"]
    for dt in ("prescription", "itemized_bill"):
        c.post(f"/api/claims/{cid}/documents", headers=hh,
               data={"doc_type": dt}, files={"file": (f"{dt}.png", _bill_png(doc_name), "image/png")})
    return cid


from services.ocr import ocr_available
if ocr_available():
    # Matching image: OCR reads the name, identity confirmed.
    cid_ok = _image_claim("Alice Menon", "Alice Menon")
    dbx = SessionLocal(); s_ok = check_identity(dbx.get(Claim, cid_ok)); dbx.close()
    ok("OCR reads image (verifiable, not skipped)", len(s_ok["unverifiable_documents"]) == 0)
    ok("OCR identity match ok", s_ok["identity_ok"] is True and s_ok["hard_mismatch"] is False)
    ok("OCR match score present", isinstance(s_ok["ocr_score"], int) and s_ok["ocr_score"] > 50)

    # Mismatched image: OCR reads a DIFFERENT name → hard mismatch, score 0.
    cid_bad = _image_claim("Frauda Impostor", "Someone Else")
    dbx = SessionLocal(); s_bad = check_identity(dbx.get(Claim, cid_bad)); dbx.close()
    ok("OCR catches image name mismatch", s_bad["hard_mismatch"] is True)
    ok("OCR mismatch score = 0", s_bad["ocr_score"] == 0)
    print("     OCR match score (ok/fraud):", s_ok["ocr_score"], "/", s_bad["ocr_score"])
else:
    print("SKIP - OCR not available in this environment")

# ---- Fraud gate via full pipeline (only when the LLM is live) ------------------
if os.getenv("GROQ_API_KEY") and LLM_LIVE:
    femail = f"fraud-{uuid.uuid4().hex[:6]}@example.com"
    ft = c.post("/api/auth/signup", json={"email": femail, "password": "Passw0rd!"}).json()["access_token"]
    fh = {"Authorization": f"Bearer {ft}"}
    c.post("/api/me/profile", headers=fh,
           json={"full_name": "Frauda Impostor", "dob": "1990-01-01", "plan_id": plan_id})
    fid = c.post("/api/claims", headers=fh, json={
        "claim_type": "pharmacy", "provider_name": "Some Pharmacy",
        "diagnosis_text": "meds", "date_of_service": "2026-07-01", "amount": 2000}).json()["id"]
    for dt, title in [("prescription", "Prescription"), ("itemized_bill", "Itemized Bill")]:
        pdf = pdf_bytes([title, "Patient: Someone Else", "Item ..... 2,000", "Date: 2026-07-01"])
        c.post(f"/api/claims/{fid}/documents", headers=fh,
               data={"doc_type": dt}, files={"file": (f"{title}.pdf", pdf, "application/pdf")})
    c.post(f"/api/claims/{fid}/submit", headers=fh)
    fresp = ai_review(fid)
    if not llm_unavailable(fresp):
        fres = fresp.json(); integ = fres.get("integrity") or {}
        ok("fraud: identity mismatch detected", integ.get("identity_match") is False)
        ok("fraud: integrity blocked", integ.get("blocked") is True)
        ok("fraud: NOT auto-approved", fres.get("verdict") != "approve")
        ok("fraud: score capped (<=40)", fres.get("final_score") <= 40)
        print("     fraud verdict:", fres.get("verdict"), "| final:", fres.get("final_score"))

print("\nALL SMOKE TESTS PASSED")
