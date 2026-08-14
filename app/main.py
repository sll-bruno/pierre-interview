from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.evaluation import public_cases, run_quality, status as evaluation_status
from app.models import (
    EvaluationRunRequest,
    FeedbackRequest,
    FeedbackResponse,
    SearchRequest,
    SearchResponse,
)
from app.search import TransactionSearch


ROOT_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT_DIR / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        app.state.search = TransactionSearch(settings)
        app.state.search_error = None
    except RuntimeError as error:
        # The UI remains available in local demo mode while the semantic index
        # is being generated. API calls clearly report the missing dependency.
        app.state.search = None
        app.state.search_error = str(error)
    yield


app = FastAPI(
    title="Pierre Semantic Transactions API",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@app.get("/", include_in_schema=False)
async def frontend() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/ai_engineer_semantic_transactions.csv", include_in_schema=False)
async def demo_transactions() -> FileResponse:
    return FileResponse(ROOT_DIR / "ai_engineer_semantic_transactions.csv")


@app.get("/health")
async def health(request: Request) -> dict[str, int | str]:
    engine: TransactionSearch | None = request.app.state.search
    if engine is None:
        return {"status": "demo", "transactions": 0}
    return {"status": "ok", "transactions": len(engine.frame)}


@app.post("/search", response_model=SearchResponse)
async def search(payload: SearchRequest, request: Request) -> SearchResponse:
    engine: TransactionSearch | None = request.app.state.search
    if engine is None:
        raise HTTPException(status_code=503, detail=request.app.state.search_error)
    return await engine.search(payload.query, payload.filters)


@app.post("/feedback", response_model=FeedbackResponse)
async def feedback(payload: FeedbackRequest, request: Request) -> FeedbackResponse:
    engine: TransactionSearch | None = request.app.state.search
    if engine is None:
        raise HTTPException(status_code=503, detail=request.app.state.search_error)
    engine.record_feedback(payload.query, payload.transaction_id, payload.relevant)
    return FeedbackResponse()


def _evaluation_engine(request: Request) -> TransactionSearch:
    engine: TransactionSearch | None = request.app.state.search
    evaluation = evaluation_status(engine, settings.evaluation_suite)
    if not evaluation["available"]:
        raise HTTPException(status_code=409, detail=evaluation["reason"])
    assert engine is not None
    return engine


@app.get("/evaluation/status")
async def get_evaluation_status(request: Request) -> dict:
    return evaluation_status(request.app.state.search, settings.evaluation_suite)


@app.get("/evaluation/cases")
async def get_evaluation_cases(request: Request, tag: str = "load") -> dict:
    _evaluation_engine(request)
    return {"cases": public_cases(settings.evaluation_suite, tag)}


@app.post("/evaluation/quality")
async def evaluate_quality(
    payload: EvaluationRunRequest, request: Request
) -> dict:
    engine = _evaluation_engine(request)
    return await run_quality(engine, settings.evaluation_suite, payload.top_k)
