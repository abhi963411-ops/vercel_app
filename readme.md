# Build and Deploy the Latency API on Vercel

This guide recreates the eShopCo telemetry API in a new folder and deploys it as a Python serverless function. It uses the supplied `q-vercel-latency.json` telemetry file.

## 1. Install prerequisites

Install Python 3.10 or newer, Node.js (which includes npm), and Git. Verify they are available in PowerShell:

```powershell
py --version
node --version
npm --version
```

Install the Vercel CLI and sign in:

```powershell
npm install --global vercel
vercel login
```

Complete the sign-in flow in your browser.

## 2. Create the project

In PowerShell, make a new project directory and its API directory:

```powershell
mkdir eshopco-latency-api
cd eshopco-latency-api
mkdir api
```

Copy `q-vercel-latency.json` into the project root. The finished layout should be:

```text
eshopco-latency-api/
  api/
    index.py
  q-vercel-latency.json
  requirements.txt
    vercel.json
```

Create `requirements.txt` with:

```text
fastapi
```

Create `vercel.json` in the project root to set CORS response headers at Vercel's deployment layer as well:

```json
{
    "$schema": "https://openapi.vercel.sh/vercel.json",
    "headers": [
        {
            "source": "/(.*)",
            "headers": [
                { "key": "Access-Control-Allow-Origin", "value": "*" },
                { "key": "Access-Control-Allow-Methods", "value": "POST, OPTIONS" },
                { "key": "Access-Control-Allow-Headers", "value": "Content-Type" }
            ]
        }
    ]
}
```

## 3. Add the FastAPI function

Create `api/index.py` with this code:

```python
import json
from pathlib import Path
from statistics import mean

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


DATA_PATH = Path(__file__).resolve().parents[1] / "q-vercel-latency.json"
with DATA_PATH.open(encoding="utf-8") as telemetry_file:
    TELEMETRY = json.load(telemetry_file)

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST"],
    allow_headers=["*"],
)


@app.middleware("http")
async def ensure_cors_origin_header(request, call_next):
    response = await call_next(request)
    if "access-control-allow-origin" not in response.headers:
        response.headers["Access-Control-Allow-Origin"] = "*"
    return response


class MetricsRequest(BaseModel):
    regions: list[str]
    threshold_ms: float = 180


def percentile_95(values: list[float]) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * 0.95
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


@app.post("/")
@app.post("/{function_path:path}")
def get_region_metrics(request: MetricsRequest) -> dict:
    results = {}
    for region in request.regions:
        records = [record for record in TELEMETRY if record["region"] == region]
        if not records:
            raise HTTPException(status_code=404, detail=f"No telemetry for region: {region}")

        latencies = [record["latency_ms"] for record in records]
        results[region] = {
            "avg_latency": mean(latencies),
            "p95_latency": percentile_95(latencies),
            "avg_uptime": mean(record["uptime_pct"] for record in records),
            "breaches": sum(latency > request.threshold_ms for latency in latencies),
        }
    return results
```

The catch-all POST route lets FastAPI match the `/api` path Vercel uses for `api/index.py`. The CORS middleware supports any origin, POST, and the headers browsers send for JSON requests. The extra middleware ensures the wildcard origin header is also present when a test client omits the `Origin` request header. The p95 calculation uses linear interpolation; a breach means latency is strictly greater than the supplied threshold.

## 4. Run it locally

Create and activate a virtual environment, then install the app and local server dependencies:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install fastapi uvicorn
```

If PowerShell blocks activation, allow it for this terminal only and activate again:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

Start the local server:

```powershell
python -m uvicorn api.index:app --reload
```

In another PowerShell terminal, send a test POST:

```powershell
$body = '{"regions":["emea","apac"],"threshold_ms":156}'
Invoke-RestMethod -Uri 'http://127.0.0.1:8000/' -Method Post -ContentType 'application/json' -Body $body
```

Stop the local server with `Ctrl+C` when finished.

## 5. Deploy to Vercel

From the project root (the directory containing `api` and `requirements.txt`), run:

```powershell
vercel
```

Answer the setup prompts. Vercel detects FastAPI, installs `requirements.txt`, and creates a preview deployment. When it is ready, publish to production:

```powershell
vercel --prod
```

The endpoint URL is your deployment domain followed by `/api`, for example:

```text
https://your-project-name.vercel.app/api
```

Use that full URL in dashboard clients; the domain root is not the function URL.

## 6. Verify the production endpoint and CORS

Replace the example domain with your production domain:

```powershell
$url = 'https://your-project-name.vercel.app/api'
$body = '{"regions":["emea","apac"],"threshold_ms":156}'
Invoke-RestMethod -Uri $url -Method Post -ContentType 'application/json' -Headers @{Origin='https://dashboard.example'} -Body $body
```

For a browser JSON request, verify the preflight response too:

```powershell
Invoke-WebRequest -UseBasicParsing -Uri $url -Method Options -Headers @{
  Origin = 'https://dashboard.example'
  'Access-Control-Request-Method' = 'POST'
  'Access-Control-Request-Headers' = 'content-type'
}
```

The response should include `Access-Control-Allow-Origin: *`; the preflight should also allow `POST` and `content-type`.

## Troubleshooting CORS

- **Use the `/api` URL.** With `api/index.py`, call `https://<deployment-domain>/api`.
- **Vercel Authentication is separate from FastAPI CORS.** For an API that outside dashboards must call, open the Vercel project settings, find Deployment Protection, and disable Vercel Authentication for the deployment environment being called. A protection page or redirect can be returned before FastAPI runs, so it will not have the app's CORS headers.
- **Check both requests.** Browsers send an `OPTIONS` preflight before many JSON POST requests. The FastAPI CORS middleware above handles it. Inspect the POST and OPTIONS response headers rather than testing with only a same-origin request.
- **Redeploy code changes.** After editing files, run `vercel --prod` again and test the production URL, not an old preview URL.

Allowing every origin is appropriate for this public sample endpoint. For a real API with private telemetry, add authentication and restrict allowed origins to the dashboards that should use it.