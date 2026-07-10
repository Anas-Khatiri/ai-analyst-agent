import logging

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator
from starlette.responses import JSONResponse

# Import configuration, logging and instrumentation
from api.routers import incidents
from infra.logging_utils import log_event

# log_event (per .agents/CONTEXT.md §3) already renders each record as a
# JSON string; format="%(message)s" emits that string verbatim instead of
# wrapping it in stdlib's default "LEVEL:name:message" prefix.
logging.basicConfig(level=logging.INFO, format="%(message)s")

app = FastAPI(title="ml-analyst-agent", version="0.1.0")
instrumentor = Instrumentator()
instrumentor.instrument(app).expose(app)

app.include_router(incidents.router)

_LOGGER = logging.getLogger(__name__)


# Health endpoints
@app.get("/health")
def health() -> JSONResponse:
    return JSONResponse(content={"status": "ok"})


@app.get("/ready")
def readiness() -> JSONResponse:
    # Placeholder for readiness checks (e.g., Redis ping)
    return JSONResponse(content={"ready": True})


@app.get("/live")
def liveness() -> JSONResponse:
    return JSONResponse(content={"live": True})


# Example ping endpoint using logger
@app.get("/ping")
def ping() -> JSONResponse:
    log_event(_LOGGER, logging.INFO, __name__, "ping", "ping_endpoint_called")
    return JSONResponse(content={"ping": "pong"})
