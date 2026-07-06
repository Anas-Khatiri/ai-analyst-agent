import structlog
from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator
from starlette.responses import JSONResponse

# Import configuration, logging and instrumentation
from api.routers import incidents
from shared.logging_config import configure_logging

app = FastAPI(title="ml-analyst-agent", version="0.1.0")
instrumentor = Instrumentator()
instrumentor.instrument(app).expose(app)

app.include_router(incidents.router)

# Initialize logging
configure_logging()
logger = structlog.get_logger(__name__)


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
    logger.info("ping endpoint called")
    return JSONResponse(content={"ping": "pong"})
