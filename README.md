# LLM Analysis Quiz Solver

This project implements an HTTP API endpoint that can:

- Receive a quiz task via POST request
- Validate a secret token for authentication
- Visit a quiz URL (with JavaScript execution via Playwright)
- Extract and process page text, links, and embedded data files
- Use an LLM to analyze data and compute the required answer
- Submit the computed answer to the quiz's submit endpoint
- Follow a chain of quiz URLs until completion or timeout (max 3 minutes)

## Features

- **Headless browser rendering**: Uses Playwright to execute JavaScript and render dynamic pages
- **Multi-format data support**: Automatically downloads and processes CSV, Excel, JSON, TXT, and PDF files
- **LLM-powered analysis**: Sends comprehensive page context (text + data) to OpenAI-compatible LLM for answer computation
- **Fallback heuristics**: Extracts answers from page text directly if LLM fails to respond
- **Payload validation**: Ensures submission payloads do not exceed 1MB limit
- **Time-aware solving**: Tracks elapsed time and respects the 3-minute deadline

## Tech Stack

- **Framework**: FastAPI + Uvicorn
- **Browser Automation**: Playwright (Chromium)
- **HTTP Client**: httpx (async-first)
- **Data Processing**: pandas, pdfplumber, openpyxl
- **LLM Integration**: OpenAI API (via AiPipe proxy)
- **Configuration**: Pydantic Settings + python-dotenv

---

## Setup

### Prerequisites

- Python 3.8+
- Virtual environment (venv or conda)

### 1. Clone the repository

```bash
git clone <YOUR_REPO_URL>
cd llm-analysis-quiz
```

### 2. Create and activate a virtual environment

**On macOS/Linux:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

**On Windows (PowerShell):**
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

This installs:
- `fastapi`, `uvicorn` for the API server
- `playwright` for headless browser rendering
- `pandas`, `openpyxl`, `pdfplumber` for data processing
- `httpx` for async HTTP requests
- `pydantic-settings`, `python-dotenv` for configuration

### 4. Configure environment variables

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

Edit `.env` with:
- `STUDENT_EMAIL`: Your email address (will be in quiz submissions)
- `EXPECTED_SECRET`: A secret string (will be used to verify requests)
- `OPENAI_API_KEY`: Your API key for OpenAI or AiPipe proxy
- `LLM_MODEL`: Model name, e.g., `gpt-4o-mini` (default is fine)

**Example `.env`:**
```dotenv
STUDENT_EMAIL=student@example.com
EXPECTED_SECRET=your-strong-random-secret
OPENAI_API_KEY=your-aipipe-api-key
LLM_MODEL=gpt-4o-mini
```

### 5. (Optional) Install Playwright browsers

If you want to use headless rendering, install the Chromium browser:

```bash
playwright install chromium
```

(The code will handle this gracefully if not installed; it will fall back to httpx-only fetching.)

---

## Running the API

Start the FastAPI server with:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

The API will be available at `http://localhost:8000`.

### Check the server is running

```bash
curl http://localhost:8000/docs
```

This opens the interactive API documentation (Swagger UI).

---

## API Endpoint

### POST /quiz

Accepts a quiz task and solves it.

**Request:**
```json
{
  "email": "your@email.com",
  "secret": "your-secret-from-env",
  "url": "https://example.com/quiz-task-1"
}
```

**Response (200 - Secret matches):**
```json
{
  "status": "ok",
  "solver_result": {
    "steps": [
      {
        "url": "https://example.com/quiz-task-1",
        "page_text_snippet": "...",
        "llm_answer_obj": {
          "answer": 42
        },
        "submit_url": "https://example.com/submit",
        "submit_status_code": 200,
        "submit_response": {
          "correct": true,
          "url": "https://example.com/quiz-task-2"
        }
      }
    ],
    "total_time_secs": 8.5,
    "within_time_limit": true
  }
}
```

**Response (403 - Invalid secret):**
```json
{
  "error": "Invalid secret."
}
```

**Response (400 - Invalid JSON):**
```json
{
  "error": "JSON must contain 'email', 'secret', and 'url' as strings."
}
```

---

---

## Testing

### Quick Test with Python Script

The easiest way to test is using the provided `test_api.py` script:

```bash
# Test locally
python test_api.py

# Test with custom secret
python test_api.py --secret "your-secret-here"

# Test against demo endpoint
python test_api.py --demo --secret "eVUyyKnAP956QwwgmWcBfBbD6cSMNW2zsvD8CnO4uYM="
```

This runs comprehensive tests including:
- ✓ Valid payload (200 OK)
- ✓ Invalid secret (403 Forbidden)
- ✓ Invalid JSON (400 Bad Request)
- ✓ Missing fields (400 Bad Request)
- ✓ Non-string fields (400 Bad Request)
- ✓ Optional: Demo endpoint test

### Manual Testing with curl

**Test 1: Valid payload (expect 200)**
```bash
curl -X POST http://127.0.0.1:8000/quiz \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "secret": "eVUyyKnAP956QwwgmWcBfBbD6cSMNW2zsvD8CnO4uYM=",
    "url": "https://httpbin.org/html"
  }'

# Expected response: 200 OK with solver_result
```

**Test 2: Invalid secret (expect 403)**
```bash
curl -X POST http://127.0.0.1:8000/quiz \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "secret": "wrong-secret",
    "url": "https://httpbin.org/html"
  }'

# Expected response: 403 Forbidden
# Response: {"error": "Invalid secret."}
```

**Test 3: Invalid JSON (expect 400)**
```bash
curl -X POST http://127.0.0.1:8000/quiz \
  -H "Content-Type: application/json" \
  -d 'not-valid-json'

# Expected response: 400 Bad Request
# Response: {"error": "Invalid JSON payload."}
```

**Test 4: Missing required field (expect 400)**
```bash
curl -X POST http://127.0.0.1:8000/quiz \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "secret": "eVUyyKnAP956QwwgmWcBfBbD6cSMNW2zsvD8CnO4uYM="
  }'

# Expected response: 400 Bad Request (missing 'url')
# Response: {"error": "JSON must contain 'email', 'secret', and 'url' as strings."}
```

**Test 5: Non-string field (expect 400)**
```bash
curl -X POST http://127.0.0.1:8000/quiz \
  -H "Content-Type: application/json" \
  -d '{
    "email": 12345,
    "secret": "eVUyyKnAP956QwwgmWcBfBbD6cSMNW2zsvD8CnO4uYM=",
    "url": "https://httpbin.org/html"
  }'

# Expected response: 400 Bad Request (email must be string)
# Response: {"error": "JSON must contain 'email', 'secret', and 'url' as strings."}
```

### Test with the Demo Endpoint

The evaluation system provides a demo endpoint at `https://tds-llm-analysis.s-anand.net/demo`:

```bash
curl -X POST http://127.0.0.1:8000/quiz \
  -H "Content-Type: application/json" \
  -d '{
    "email": "22f3001852@ds.study.iitm.ac.in",
    "secret": "eVUyyKnAP956QwwgmWcBfBbD6cSMNW2zsvD8CnO4uYM=",
    "url": "https://tds-llm-analysis.s-anand.net/demo"
  }'

# Expected response: 200 OK with solver_result showing the quiz was solved
```

### Local Testing (using Python requests)

```python
import httpx

# Test valid request
response = httpx.post(
    "http://127.0.0.1:8000/quiz",
    json={
        "email": "test@example.com",
        "secret": "eVUyyKnAP956QwwgmWcBfFbD6cSMNW2zsvD8CnO4uYM=",
        "url": "https://tds-llm-analysis.s-anand.net/demo"
    },
    timeout=120
)

print(f"Status: {response.status_code}")
print(f"Response: {response.json()}")

# Check if solver succeeded
if response.status_code == 200:
    data = response.json()
    if data.get("status") == "ok":
        result = data["solver_result"]
        print(f"Steps completed: {len(result['steps'])}")
        print(f"Time taken: {result['total_time_secs']}s")
        print(f"Within 3-minute limit: {result['within_time_limit']}")
```

---

## Architecture

### `app/main.py`
- FastAPI app with `/quiz` POST endpoint
- Validates JSON, checks secret, delegates to solver

### `app/config.py`
- Pydantic Settings for environment configuration
- Loads from `.env` file

### `app/browser.py`
- `fetch_page(url)`: Fetches HTML and text (httpx + Playwright fallback)
- Detects JavaScript-heavy pages and renders them headlessly
- Returns `(html, visible_text, links)`

### `app/quiz_solver.py`
- `solve_quiz_chain(email, secret, start_url)`: Main solver logic
- Decodes base64-encoded content (atob blocks)
- Downloads data files (CSV, Excel, JSON, PDF, TXT)
- Builds LLM context and calls OpenAI API
- Extracts answers using heuristics if needed
- Submits to quiz endpoint and follows next URL
- Respects 3-minute time limit

### `app/llm_client.py`
- `ask_llm_for_answer(quiz_context)`: Async LLM client
- Sends context to AiPipe OpenAI-compatible endpoint
- Parses JSON response and returns `{"answer": ...}`

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `STUDENT_EMAIL` | Yes | — | Your email address |
| `EXPECTED_SECRET` | Yes | — | Secret string for request verification |
| `OPENAI_API_KEY` | Yes | — | API key for AiPipe or OpenAI |
| `LLM_MODEL` | No | `gpt-4o-mini` | LLM model name |
| `MAX_QUIZ_DURATION_SECS` | No | `170` | Max time per quiz chain (seconds) |
| `ENABLE_LLM_RETRY` | No | `false` | Enable strict retry if first LLM call returns null |

---

## Troubleshooting

### Playwright not found
```
RuntimeError: Playwright import failed
```
**Fix**: Run `playwright install chromium` to download the browser.

### API key errors
```
RuntimeError: AiPipe HTTP error: 401 Unauthorized
```
**Fix**: Check your `OPENAI_API_KEY` in `.env` is correct and has valid credentials.

### Timeout errors
If quiz solving takes longer than `MAX_QUIZ_DURATION_SECS` (default 170s), the solver will stop. Increase this in `.env` if needed (but the evaluation system has a strict 3-minute limit).

### LLM response parsing errors
If the LLM returns unexpected JSON, the code tries multiple extraction strategies:
1. Looks for `"answer"` key in response
2. Falls back to heuristic extraction from page text
3. If `ENABLE_LLM_RETRY=true`, retries with stricter instructions

---

## Deployment

### Docker (Optional)

Create a `Dockerfile`:
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt && playwright install chromium
COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Build and run:
```bash
docker build -t llm-analysis-quiz .
docker run -p 8000:8000 --env-file .env llm-analysis-quiz
```

### Cloud Deployment

For deployment on platforms like Render, Railway, or AWS:
1. Set environment variables via platform dashboard (do NOT commit `.env`)
2. Ensure Playwright is installed (add `playwright install chromium` to build steps)
3. Use `uvicorn app.main:app --host 0.0.0.0 --port 8000`

---

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.

---

## Submission Checklist

Before submitting to the evaluation system:

- [ ] Update `.env` with your actual email and secret
- [ ] Ensure `LICENSE` file exists (MIT)
- [ ] Test locally: `curl` or Python script against `/quiz` endpoint
- [ ] Test with demo: `POST` to `https://tds-llm-analysis.s-anand.net/demo`
- [ ] Ensure repo is public (or will be at evaluation time)
- [ ] Verify `.env` with real secrets is NOT committed (add to `.gitignore`)
- [ ] Fill out the Google Form with:
  - Your email
  - `EXPECTED_SECRET` value
  - API endpoint URL (e.g., `https://your-domain.com/quiz`)
  - GitHub repo URL

---

## Notes

- The solver respects the 3-minute deadline from the evaluation system; local testing may be faster
- The LLM context is limited to ~4000 characters per file to avoid excessive token usage
- Submission payloads are validated to be under 1MB
- All timestamps and tracebacks are logged for debugging

For questions or issues, refer to the code comments in `app/` files or the inline documentation.
