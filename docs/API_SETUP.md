# API Credential & Source Setup Guide

An authoritative guide to configured credentials, public keyless endpoints, and official registration processes for all 10 pipeline data sources.

---

## 🟢 SECTION 1 — Already Configured Sources

These providers have their authentication credentials configured in `.env` and loaded automatically via `python-dotenv`:

| Source | Environment Variable | Auth Method | Code Reader Location | Test Command |
| :--- | :--- | :--- | :--- | :--- |
| **Zenserp** | `ZENSERP_API_KEY` | Query Parameter (`apikey`) | `src/scrapers/adapters/zenserp_adapter.py` | `python src/test_connectivity.py` |
| **Newsflash** | `NEWSFLASH_API_KEY` | Bearer Header (`Authorization: Bearer <key>`) | `src/scrapers/adapters/news_adapters.py` | `python src/test_connectivity.py` |
| **GNews** | `GNEWS_API_KEY` | Query Parameter (`apikey`) | `src/scrapers/adapters/news_adapters.py` | `python src/test_connectivity.py` |
| **The Guardian** | `GUARDIAN_API_KEY` | Query Parameter (`api-key`) | `src/scrapers/adapters/news_adapters.py` | `python src/test_connectivity.py` |
| **USAJOBS** | `USAJOBS_API_KEY`<br>`USAJOBS_API_EMAIL` | Required Headers (`Host`, `User-Agent`, `Authorization-Key`) | `src/scrapers/adapters/jobs_adapters.py` | `python src/test_connectivity.py` |
| **Indeed (RapidAPI)** | `RAPIDAPI_KEY` | RapidAPI Headers (`x-rapidapi-host`, `x-rapidapi-key`) | `src/scrapers/adapters/jobs_adapters.py` | `python src/test_connectivity.py` |
| **Active Jobs DB (RapidAPI)** | `RAPIDAPI_KEY` | RapidAPI Headers (`x-rapidapi-host`, `x-rapidapi-key`) | `src/scrapers/adapters/jobs_adapters.py` | `python src/test_connectivity.py` |

---

## 🤖 SECTION 1.5 — Multi-Tier LLM Provider Chain (Sequential Fallback)

The pipeline employs a **hybrid deterministic-first strategy**, falling back to a sequential multi-tier LLM hierarchy only for unstructured or incomplete records:

1. **Primary Provider**: **Google Gemini** (`GEMINI_API_KEY`, default model: `gemini-2.0-flash` / `gemini-2.5-flash`)
2. **Secondary Fallback**: **Groq** (`GROQ_API_KEY`, default model: `llama-3.1-8b-instant`)
3. **Tertiary Fallback**: **OpenRouter** (`OPENROUTER_API_KEY`, default model: `openai/gpt-3.5-turbo`)

**Live Verification Command**:
```bash
python -m src.llm.probe
```

---

## 🌐 SECTION 2 — Public / No-Key Sources

These sources require **no API keys** and are accessed directly via their official public read endpoints:

### 1. Arbeitnow Job Board API
- **Category**: Jobs
- **Endpoint**: `https://www.arbeitnow.com/api/job-board-api`
- **Auth**: None
- **Response Mapping**: Extracts `title`, `company_name`, `created_at`, `url`, `location`, `remote`, and `slug` with automatic Unix timestamp normalization.

### 2. DataCube AI
- **Category**: News / Datasets
- **Endpoint**: `https://datacube.ai/api/v1/news`
- **Auth**: None
- **Response Mapping**: Maps `title`, `url`, `published_at`, and `summary` into the standard raw candidate dictionary.

### 3. Noozra
- **Category**: News
- **Endpoint**: `https://noozra.com/api/articles?category=tech&limit=100&before=`
- **OpenAPI Spec**: `https://noozra.com/api/openapi.json`
- **Auth**: None
- **Provenance Rule**: If Noozra omits a canonical source URL for a record, the adapter marks it unresolved and omits it from final output.

### 4. AI Dev Jobs
- **Category**: Jobs
- **Endpoint**: `https://aidevboard.com/api/v1/jobs`
- **Auth**: None
- **Response Mapping**: Extracts `title`, `company`, `created_at`, `url`, and `is_remote`.

### 5. Freehire
- **Category**: Jobs
- **Endpoint**: `https://freehire.me/api/v1/jobs`
- **Auth**: None
- **Envelope Structure**: `{"data": [...], "meta": {"total": ..., "limit": ..., "offset": ...}}`

### 6. Artificial Intelligence Jobs
- **Category**: Jobs
- **Endpoint**: `https://artificialintelligencejobs.net/feed/`
- **Auth**: None (Public RSS feed)
- **Status**: Public community jobs feed.

---

## 📝 SECTION 3 — Missing Credentials & Official Registration Process

If an API key is revoked or needs to be provisioned for a new deployment environment, use the official registration workflows below:

### 1. USAJOBS Search API
- **Official Documentation**: [https://developer.usajobs.gov/api-reference/get-api-search](https://developer.usajobs.gov/api-reference/get-api-search)
- **Official Registration Page**: [https://developer.usajobs.gov/APIRequest/Index](https://developer.usajobs.gov/APIRequest/Index)
- **Signup Requirements**: Requires submitting an API Request with your email, application description, and name.
- **Environment Variables to Set**:
  ```env
  USAJOBS_API_KEY=<issued_authorization_key>
  USAJOBS_API_EMAIL=<email_used_during_request>
  ```
- **Required Headers**:
  - `Host: data.usajobs.gov`
  - `User-Agent: <USAJOBS_API_EMAIL>`
  - `Authorization-Key: <USAJOBS_API_KEY>`

### 2. The Guardian Open Platform
- **Official Documentation**: [https://open-platform.theguardian.com/documentation/](https://open-platform.theguardian.com/documentation/)
- **Registration Page**: [https://open-platform.theguardian.com/access/](https://open-platform.theguardian.com/access/)
- **Signup Requirements**: Free Developer tier tier with email verification.
- **Environment Variable**: `GUARDIAN_API_KEY`

### 3. GNews API
- **Official Documentation**: [https://gnews.io/docs/v4](https://gnews.io/docs/v4)
- **Registration Page**: [https://gnews.io/register](https://gnews.io/register)
- **Signup Requirements**: Free tier (100 requests/day).
- **Environment Variable**: `GNEWS_API_KEY`

### 4. Newsflash
- **Official Portal**: [https://newsflash.io](https://newsflash.io)
- **Environment Variable**: `NEWSFLASH_API_KEY`

### 5. Zenserp
- **Official Portal**: [https://zenserp.com](https://zenserp.com)
- **Environment Variable**: `ZENSERP_API_KEY`
- **Usage Rule**: Candidate discovery and query search only. Downstream records must resolve to legitimate destination URLs.

---

## 🛡️ Zero-Hallucination & Provenance Guarantees
- **Unified 24h Freshness Filter**: All records pass through `now_utc - 24h <= published_date <= now_utc`.
- **Deterministic Role Classification**: Jobs are categorized into `Engineering`, `Research`, `Product`, or `Other` without LLMs.
- **Audit Logging**: Per-source candidate counts, fresh counts, stale counts, and heuristic date flags are logged transparently.
