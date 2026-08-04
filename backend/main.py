"""FastAPI application entrypoint.

Run from the backend/ directory:  uvicorn main:app --reload
Tables are created and demo data is seeded automatically on first start.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import APP_NAME, EXTRA_CORS_ORIGINS, FRONTEND_URL
from database import Base, SessionLocal, engine
from routes import admin, auth, consent, customer, oauth, twilio_callback
from seed import seed_if_empty
from sqlalchemy import inspect, text


def _migrate_schema():
    """Lightweight SQLite migrations for columns added after first deploy."""
    if not str(engine.url).startswith("sqlite"):
        return
    insp = inspect(engine)
    if "users" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("users")}
    if "phone" not in cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE users ADD COLUMN phone VARCHAR"))


app = FastAPI(title=f"{APP_NAME} — Insurance Pre-Authorization (Demo)")

_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:8080",
    "http://127.0.0.1:8080",
    FRONTEND_URL,
] + EXTRA_CORS_ORIGINS

app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(set(_origins)),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(oauth.router)
app.include_router(consent.router)
app.include_router(customer.router)
app.include_router(admin.router)
app.include_router(twilio_callback.router)


@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)
    _migrate_schema()
    db = SessionLocal()
    try:
        seed_if_empty(db)
    finally:
        db.close()


@app.get("/api/health")
def health():
    return {"status": "ok"}
