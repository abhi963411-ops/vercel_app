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
    expose_headers=["Access-Control-Allow-Origin"],
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
def get_region_metrics(request: MetricsRequest) -> dict[str, dict[str, dict[str, float | int]]]:
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
    return {"regions": results}


@app.get("/home")
def home():
    return {"app": "it is running very well"}