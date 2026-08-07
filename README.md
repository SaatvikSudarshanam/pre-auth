# PreAuthIQ — Insurance Pre-Authorization (Demo)

A full-stack demo of **end-to-end insurance pre-authorization** with a
**human-in-the-loop** multi-agent AI pipeline. Customers submit pre-auth requests
with documents; an admin reviews them assisted by **six specialized AI agents**
(the five turnaround agents plus a **fraud / document-integrity agent**). The AI is
**strictly isolated to the admin side** — the customer app never sees, calls, or
bundles any AI code.

- **Backend:** FastAPI + SQLAlchemy (SQLite), local disk storage for uploads
- **Frontend:** React (Vite) + Tailwind CSS — a landing page, login, and the two app trees
- **LLM:** Groq (OpenAI-compatible), `llama-3.3-70b-versatile`, JSON-mode output
- **OCR:** RapidOCR (ONNX, CPU) + PyMuPDF — reads images and scanned PDFs
- **Customer auth:** Google OAuth **and** email/password
- **Privacy:** privacy + cookie policies, cookie consent banner with server-side tracking
- **Deploy:** Docker Compose (frontend on 8080, backend on 8068)

> ⚠️ **Rotate the shared secrets.** If the Groq key or Google client secret were
> pasted into a chat or committed anywhere, regenerate them (Groq console / Google
> Cloud Console) before real use. Secrets live only in `backend/.env`, which is
> git-ignored.
>
> ⚠️ **Demo auth — replace before production.** Admin credentials are checked
> against `.env`. There is no email verification, rate limiting, refresh-token
> rotation, RBAC beyond customer/admin, or real PHI handling. Do not deploy as-is.

---

## The five AI agents

The "Run AI Review" action runs a sequential pipeline; each agent is a focused LLM
call with its own prompt file in [`backend/prompts/agents/`](backend/prompts/agents/),
and every run is persisted to the `agent_runs` audit table.

| # | Agent | Role |
|---|-------|------|
| 1 | **Claims Registration Agent** | Validate & normalize the incoming request |
| 2 | **Doc Completeness Agent** | Assess whether supporting documents are present/usable |
| 3 | **Document Integrity Agent** | Fraud / authenticity: cross-check identity & consistency |
| 4 | **Coverage Verification Agent** | Verify against plan coverage, exclusions, limits |
| 5 | **Pre-Authorization Agent** | Adjudicate — advisory verdict (approve / reject / needs info) |
| 6 | **Denial Communication Agent** | Draft the plain-language customer message |

The Pre-Authorization Agent's verdict and confidence drive the overall
recommendation; the Denial Communication Agent's text pre-fills the customer message.
The landing page highlights the original five turnaround agents (from the product
strip); the Document Integrity Agent is the sixth, fraud-focused agent.

### Document integrity & fraud gate

To stop fake or mismatched documents from getting approved, the pipeline pairs the
Document Integrity Agent with a **deterministic** backend cross-check
([`backend/services/integrity.py`](backend/services/integrity.py)):

- It reads the text out of each submitted document and checks that the **account
  holder's name** (the identity the session is logged in as) actually appears on the
  ID proof and bills, that amounts/dates are consistent, and that the provider matches.
- **OCR is built in** ([`backend/services/ocr.py`](backend/services/ocr.py)):
  **image uploads (JPG/PNG) and scanned PDFs are read** with open-source
  **RapidOCR** (ONNX, CPU, models bundled — no Tesseract binary), and scanned PDFs
  are rasterized with **PyMuPDF** first. Each OCR'd document carries a confidence,
  and the integrity summary reports an **OCR match score** (how confidently the
  account name was read from the documents). PDFs with embedded text skip OCR.
- If the name appears on **none** of the readable documents (or a readable ID proof
  doesn't match), that's a **hard identity mismatch**. The system then **blocks
  auto-approval** — any "approve" is downgraded to "needs info", the final score is
  capped at 40, and a loud flag is raised for the human reviewer. The admin sees a
  red **integrity banner** (with the OCR match score) and an `IDENTITY MISMATCH` chip.
- This is enforced deterministically, so it holds even if the LLM is wrong or is
  prompt-injected into saying "approve".

**Document verification.** Every document on a claim goes through three layers before
adjudication, and only the middle one involves a model:

| Layer | Module | What it establishes |
|---|---|---|
| Forensics | `services/forensics.py` | Provenance of the **file**: SHA-256, PDF Producer/Creator against a generator fingerprint list (image editors, online invoice builders, diffusion tools), incremental-update count, image-only-PDF detection, EXIF camera vs. missing/stripped metadata, PNG generation-prompt chunks and C2PA genAI markers, specimen/template watermark text, letterhead density, **stamp/seal ink detection**, digital-signature fields, and error-level analysis for spliced edits. |
| Extraction | `prompts/agents/extraction.txt` | Transcription of the **content** — patient, provider, address, GSTIN, invoice number/date, amount — plus perceptual observations (tampering, watermark text, **stamp/seal presence and its text**, how machine-generated the page looks). The model is never told what any value should be, and never asked whether one is valid. |
| Cross-check | `services/crosscheck.py` | Exact comparison against the authoritative values: patient name vs. the signed-in Google profile, hospital vs. the claim's provider, GSTIN mod-36 checksum (`services/gstin.py`), PIN ↔ GSTIN-state agreement (`services/address.py`), claimed amount vs. documented total, invoice dates vs. date of service, **stamp presence on document types that should carry one**, and byte-identical reuse across claims. |

**Stamp / seal detection.** A hospital bill, prescription, or discharge summary is
stamped at the counter and signed by the issuing officer; a page that was printed or
generated and never physically handled carries neither. Two independent observers
run: `forensics.py` counts saturated mid-luminance ink (stamp pad blue/violet, pen
red) that neither black print nor white paper produces, and reports its hue, coverage
and position; the extraction agent reports what it can *see*, which catches black-ink
stamps the colour test cannot. Either one satisfies the check. Two things exempt a
document — a digital signature field, and an explicit "computer generated / no
signature required" note, both of which large hospitals genuinely issue. Absence is
scored `medium`: plenty of legitimate documents are unstamped, so it earns its weight
in combination rather than alone.

Name matching (`services/matching.py`) is token-based with a proportional edit budget,
so `Rishitha Sajjapurarn` still matches `Sri Rishitha Sajjapuram` (OCR rn/m) and
`Apollo Hospitals Enterprise Ltd` still matches a claim for `Apollo Hospital`, while
`Sita Rama` does not match `Sita Ram`.

Each check reports `pass | fail | warn | unknown`. **`unknown` is never a pass** — a
blank or unreadable document scores strictly worse than a clean one, which is what
stops an empty upload from coasting through. A `critical` failure (fabricated GSTIN,
`SPECIMEN` watermark, a file already used on another claim, a different patient's
name) blocks auto-approval outright and its specific reason becomes the denial text.
Results are cached on the `documents` row, so a re-review costs no extra LLM calls.

**Honest limitations (demo).** Reuse detection is exact-hash only — a re-photographed
or re-saved bill will not collide, so it is a floor rather than a ceiling. Address
validation is offline: it proves internal consistency (the PIN and the GSTIN agree on
the state), not that the building exists. Error-level analysis is a heuristic that
high-contrast line art can trip, which is why it never reaches `critical` on its own.
Stamp detection establishes *presence*, not authenticity — it does not read the stamp,
match it to the hospital, or notice one pasted in from another document; absence is
the informative direction. There is no issuer/registry lookup, so a well-formed GSTIN
that passes its checksum is not confirmed to belong to the named hospital. A determined forger who produces a
fully self-consistent fake still needs the human reviewer. Transient LLM errors are
retried with backoff, and if extraction is unavailable entirely, verification degrades
to forensics-only rather than failing the review.

---

## Quick start (local)

You need **Python 3.10+** and **Node 18+**.

### 1. Secrets

```bash
cp .env.example backend/.env
```

Set in `backend/.env`:
- `GROQ_API_KEY` — from https://console.groq.com
- `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`
- `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER` — for the voice call notification flow

The Google **Authorized redirect URI** must exactly match:

```
http://localhost:8068/rbac/oauth/google/callback
```

### 2. Twilio voice setup (same time as email)

When an admin saves a decision, the app sends the customer email via EmailJS **and** triggers a Twilio voice call at the same time.

**Setup in `backend/.env`:**

```bash
# Your Twilio Account SID (from https://console.twilio.com/)
TWILIO_ACCOUNT_SID=ACfc22635530700e9b1fdef852f3f37886

# Your Twilio Auth Token (from https://console.twilio.com/)
TWILIO_AUTH_TOKEN=1638ce0ebdab9e3bb89b924a98c47c29

# Your Twilio phone number (the "from" number, where calls originate)
# Must be voice-enabled and in E.164 format
TWILIO_PHONE_NUMBER=+17372212163

# Static test phone number for development (optional, defaults to +919014582844)
# Used when customer has no phone on file — allows testing without profile updates
TWILIO_TEST_PHONE_NUMBER=+919014582844

# For trial accounts ONLY: the callback URL where Twilio fetches TwiML
# See "Trial account setup" section below. Leave empty for paid accounts.
TWILIO_CALLBACK_URL=
```

**Customer phone (collected per-user):**

Each customer enters their mobile number when completing their profile. The app stores it in E.164 format (e.g. `+919014582844`) and uses that number as the "to" destination for Twilio voice calls.

**For testing:** If a customer has no phone on file, the system automatically uses `TWILIO_TEST_PHONE_NUMBER`. This lets you test the full flow without updating each customer's profile.

**Trial account setup (required for trial accounts):**

Twilio trial accounts cannot use inline TwiML (sending the voice script directly). Instead, they must fetch it via a callback URL. To make this work locally:

1. **Install ngrok** (free tunneling tool):
   ```bash
   # macOS / Linux:
   brew install ngrok
   
   # Windows: download from https://ngrok.com/download or
   choco install ngrok
   ```

2. **Start ngrok** (in a separate terminal):
   ```bash
   ngrok http 8068
   ```
   This will output something like:
   ```
   Forwarding    https://abc123xyz.ngrok.io -> http://localhost:8068
   ```

3. **Copy the HTTPS URL** (e.g., `https://abc123xyz.ngrok.io`) and set in `backend/.env`:
   ```bash
   TWILIO_CALLBACK_URL=https://abc123xyz.ngrok.io/api/twilio/twiml
   ```

4. **Restart Docker or the backend**:
   ```bash
   docker compose down
   docker compose up -d backend frontend
   ```

5. **Test a voice call**: Submit a claim, review as admin, and save the decision. Twilio will call your backend via ngrok to fetch the voice script.

**Note:** ngrok's free tier generates a new URL each time. If you restart ngrok, update `TWILIO_CALLBACK_URL` in `backend/.env` and restart the backend.

**Paid account setup (simpler):**

If you upgrade to a paid Twilio account, leave `TWILIO_CALLBACK_URL` empty and the system will use inline TwiML (no ngrok needed).

**Trial account note:**

If using a Twilio trial account, you **must verify each destination phone number** in the Twilio Console first, or calls will be rejected. Go to Phone Numbers → Verified Caller IDs and add the numbers you want to test with.

### 3. Backend (port 8068)

```bash
cd backend
python -m venv .venv
# Windows:        .venv\Scripts\activate
# macOS / Linux:  source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8068
```

First start creates `app.db`, seeds 3 plans, 2 demo customers, and 3 sample requests
(with generated PDFs and two completed agent-pipeline reviews).

### 4. Frontend (port 5173)

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173**. Vite proxies `/api/*` to the backend on 8068.

---

## Quick start (Docker)

Make sure **Docker Desktop is running**, then:

```bash
cp .env.example backend/.env      # fill in GROQ_API_KEY + Google creds
docker compose up --build
```

- Frontend: **http://localhost:8080**
- Backend / OAuth callback: **http://localhost:8068**

The frontend container (nginx) serves the built SPA and proxies `/api` to the backend
container. Uploaded files and the SQLite DB persist in the `backend_storage` volume.
The backend image installs OCR (RapidOCR/ONNX + PyMuPDF) and the system libraries it
needs (`libgl1`, `libglib2.0-0`, `libgomp1`), so the first build is a bit larger/slower.

For Docker, set `FRONTEND_URL=http://localhost:8080` — the compose file already does
this. Keep the same Google redirect URI (`http://localhost:8068/...`); the browser
reaches the backend directly on 8068.

Useful commands:

```bash
docker compose up --build          # build + run
docker compose up -d --build       # detached
docker compose logs -f backend     # tail backend logs
docker compose down                # stop
docker compose down -v             # stop + wipe the storage volume (fresh seed next up)
```

---

## Demo credentials

| Role     | Where          | Credentials                                             |
| -------- | -------------- | ------------------------------------------------------- |
| Customer | `/app/login`   | **Continue with Google**, or `alice@example.com` / `ravi@example.com` — password `Passw0rd!` |
| Admin    | `/admin/login` | `admin` / `admin@2026` (from `.env`)                    |

New customers can sign up with email/password or Google. After first sign-in you
complete a short profile (name, DOB, plan) and a member ID (`MEM-2026-XXXX`) is issued.

### Twilio voice notification flow

When an admin saves a decision, the app sends **both email and voice call**:

| When | From | To | How |
|------|------|----|----|
| **Email** | EmailJS | Customer's email (stored at signup) | Immediately via EmailJS API |
| **Voice call** | `TWILIO_PHONE_NUMBER` (your account) | Customer's phone (entered in profile) | Immediately via Twilio API |

The customer's phone number is collected during profile completion in E.164 format (e.g. `+919014582844`). If the customer has no phone on file or Twilio is not configured, the call is skipped gracefully and the user sees a message.

---

## Routes

| Path              | Access   | Purpose |
| ----------------- | -------- | ------- |
| `/`               | Public   | Landing page (product + the five agents) |
| `/privacy`, `/cookies` | Public | Policy pages |
| `/app/login`      | Public   | Customer login (Google + email/password) |
| `/app/oauth`      | Public   | Google OAuth return target |
| `/app/*`          | Customer | Dashboard, New Request (stepper), request detail |
| `/admin/*`        | Admin    | Queue, claim review, agent pipeline, decision |

### Customer flow

Sign in → complete profile → submit a pre-auth request through a 3-step stepper
(details → documents → review). 

**Phone confirmation**: During the review step, customers confirm their mobile number (in E.164 format, e.g. `+919876543210`) — this is the number used for voice call and SMS notifications when the admin makes a decision.

The uploads step shows exactly which document types
the request type requires; **submission is blocked** (with the missing list) until
all are attached — a deterministic backend rule check, **not** the LLM. The detail
page shows a status timeline, the admin's plain-language message once decided, and —
when *More Info Needed* — an upload control that returns the request to *Under Review*.

**Re-verification on "More Info Needed"**: When customers upload additional documents in response to a "More Info Needed" status, they can confirm or update their phone number at that time as well.

### Admin flow

Login → queue (oldest-first, status filters, stats strip) → claim review (document
viewer + claim/customer/plan panels) → **Run AI Review** runs the 6-agent pipeline →
result modal (verdict pill, radial final-score gauge, reasoning, flags, citations) and
an **Agent pipeline** panel showing each agent's output, status, and latency →
decision panel (Approve / Reject / Request More Info) with an editable, AI-prefilled
customer message. Saving records the action and whether the admin agreed with the AI.

---

## Scoring

The displayed score never trusts the LLM's confidence alone:

- **`deterministic_score`** (0–100), 20 pts each: required docs present, category
  covered, amount within remaining annual limit, no date/amount inconsistency flagged,
  and documents verified authentic. The last component is scored on a curve from the
  verification risk rather than pass/fail — one ambiguous OCR character should not
  cost the same as a fabricated GSTIN — and scores **0** when verification did not
  run at all, so "we could not check" never reads as "we checked and it was fine".
- **`ai_confidence`** (0–100): the Pre-Authorization Agent's confidence.
- **`final_score = round(0.5 × ai_confidence + 0.5 × deterministic_score)`**, shown
  with the component breakdown.

---

## Privacy & consent

- **Privacy Policy** (`/privacy`) and **Cookie Policy** (`/cookies`).
- A **cookie consent banner** appears until a choice is made (or the policy version
  changes). "Accept all" / "Necessary only" both POST to `/api/consent`, which records
  the policy, version, choice, timestamp, and user agent in the `consents` table
  (linked to the user when signed in, else to an anonymous client id).
- Policy versions come from `/api/policies` and are set via `PRIVACY_POLICY_VERSION`
  / `COOKIE_POLICY_VERSION` — bump them to force re-consent.

---

## Architecture & isolation

1. **LLM isolation.** All AI logic lives in `backend/services/` — `llm_client.py`
   (the only place that calls an LLM), `agents.py` (the 6-agent pipeline), and
   `ai_review.py` (the provider façade). These are imported **only** by admin routes
   ([`backend/routes/admin.py`](backend/routes/admin.py)). On the frontend, the entire
   admin tree is **lazy-loaded** ([`frontend/src/App.jsx`](frontend/src/App.jsx)), so
   AI code/strings/endpoints are code-split into a separate chunk (`AdminApp-*.js`)
   the customer app never downloads. (Verified: the customer bundle contains no
   `ai-review`, `groq`, `verdict`, `pre_authorization`, or `/api/admin` strings.)
2. **Provider abstraction.** `LLMProvider.review_claim(context)` with `GroqProvider`
   (runs the pipeline) and a `ClaudeProvider` stub, selected by `LLM_PROVIDER`.
3. **Prompts in files.** One prompt per agent in `backend/prompts/agents/`.
4. **Plan rules are DB truth.** Every agent receives the claimant's plan rules
   serialized from the database; agents are instructed never to invent policy.
5. **Secrets in `.env`.** Git-ignored; see `.env.example`.
6. **Audit log.** Every agent run (`agent_runs`), AI review (`ai_reviews`), admin
   decision (`admin_actions`), and consent event (`consents`) is timestamped and kept.

### Access control & ports

Customer JWTs carry `role=customer`; admin JWTs carry `role=admin`. The `/api/admin/*`
router returns `403` for any non-admin token. Backend runs on **8068** (matches the
Google redirect URI and serves `/rbac/oauth/google/callback`); the frontend runs on
**5173** (dev) or **8080** (Docker/nginx).

---

## Project structure

```
backend/
  main.py  config.py  database.py  models.py  schemas.py  security.py
  routes/    auth.py  oauth.py  consent.py  customer.py  admin.py
  services/  llm_client.py  agents.py  ai_review.py  context.py
             scoring.py  completeness.py  documents.py  ocr.py  integrity.py
             document_review.py  verification.py  forensics.py  crosscheck.py
             matching.py  address.py  gstin.py  toon.py
  prompts/agents/  registration.txt  completeness.txt  integrity.txt
                   extraction.txt  coverage.txt  preauthorization.txt  denial.txt
  seed.py  smoke_test.py  verify_documents.py  verify_gstin.py  Dockerfile
frontend/
  src/
    App.jsx  main.jsx  index.css
    lib/     http.js  auth.js  api.js  format.js
    components/  ui.jsx  RadialGauge.jsx  ConsentBanner.jsx  PolicyShell.jsx
    routes/  Landing.jsx  Privacy.jsx  Cookies.jsx
    routes/app/    Login  OAuthCallback  CompleteProfile  Dashboard  NewClaim  ClaimDetail  AppLayout
    routes/admin/  AdminApp  AdminLogin  AdminLayout  Queue  ClaimReview  adminApi.js
  Dockerfile  nginx.conf
docker-compose.yml
.env.example
```

## Tests

A backend smoke test exercises the full flow (signup → profile → request → upload →
submit gate → **live 6-agent AI review** → admin decision → more-info round-trip →
access control). With `GROQ_API_KEY` set it calls Groq for real:

```bash
cd backend && python smoke_test.py
```

Two offline scripts verify the deterministic layers with no API key and no network
— run them after touching any validation rule:

```bash
cd backend
python verify_documents.py   # name/org matching, address, cross-checks, forensics
python verify_gstin.py       # GSTIN mod-36 checksum in isolation
```

## Seed data

| Plan       | Annual limit | Deductible | Co-pay | Covers | Pre-auth |
| ---------- | ------------ | ---------- | ------ | ------ | -------- |
| Basic Care | ₹2,00,000    | ₹10,000    | 20%    | hospitalization, pharmacy | yes |
| Silver PPO | ₹5,00,000    | ₹5,000     | 10%    | hospitalization, procedures, pharmacy, lab | procedures above ₹50,000 |
| Gold HMO   | ₹10,00,000   | ₹0         | 5%     | all | no |

Required documents per request type: hospitalization → itemized bill, discharge
summary, ID proof · procedure → prescription, itemized bill, ID proof · pharmacy →
prescription, itemized bill · pre-auth request → prescription, ID proof.

---

## Non-goals

No EDI/FHIR, email, payments, multi-tenancy, cloud deployment config beyond Docker
Compose, or real PHI handling.
