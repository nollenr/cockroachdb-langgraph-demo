"""FastAPI surface for the interactive ReturnFlow presentation."""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from typing import Literal
from urllib.parse import urlparse
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field

from product_returns.approval_store import record_manager_decision
from langchain_cockroachdb import CockroachDBSaver

from product_returns.demo_api_store import (
    create_submission,
    list_demo_orders,
    load_run_snapshot,
    reset_demo_run,
)
from product_returns.graph_version import CURRENT_GRAPH_VERSION
from product_returns.failure_injection import request_recovery_resume
from product_returns.inspection import render_run_inspection_sql
from product_returns.runtime import ReturnWorkflowRuntime, WorkflowDispatcher


class ReturnSubmission(BaseModel):
    customer_external_id: str = Field(min_length=1, max_length=100)
    order_number: str = Field(min_length=1, max_length=100)
    request_text: str = Field(min_length=1, max_length=4000)
    failure_node: Literal[
        "lookup_order", "retrieve_policy", "assess_fraud", "issue_refund"
    ] | None = None


class ManagerDecisionRequest(BaseModel):
    decision: Literal["approved", "rejected"]
    decided_by: str = Field(default="manager.demo", min_length=1, max_length=200)
    decision_note: str | None = Field(default=None, max_length=2000)


def _connection_url() -> str:
    value = os.environ.get("CRDB_APP_URL", "").strip()
    parsed = urlparse(value)
    if parsed.username != "product_returns_app":
        raise RuntimeError("CRDB_APP_URL must use product_returns_app")
    if parsed.path.lstrip("/") != "product_returns":
        raise RuntimeError("CRDB_APP_URL must target product_returns")
    return value


@asynccontextmanager
async def lifespan(app: FastAPI):
    connection_url = _connection_url()
    runtime = await asyncio.to_thread(ReturnWorkflowRuntime, connection_url)
    dispatcher = WorkflowDispatcher(runtime)
    app.state.connection_url = connection_url
    app.state.dispatcher = dispatcher
    dispatcher.start()
    try:
        yield
    finally:
        dispatcher.stop()


app = FastAPI(
    title="ReturnFlow API",
    description="Durable product-return workflow API backed by LangGraph and CockroachDB.",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy", "graph_version": CURRENT_GRAPH_VERSION}


@app.get("/demo/orders")
async def demo_orders(request: Request):
    orders = await asyncio.to_thread(
        list_demo_orders,
        request.app.state.connection_url,
    )
    return jsonable_encoder({"orders": orders})


@app.post("/returns", status_code=status.HTTP_202_ACCEPTED)
async def submit_return(payload: ReturnSubmission, request: Request):
    try:
        created = await asyncio.to_thread(
            create_submission,
            request.app.state.connection_url,
            customer_external_id=payload.customer_external_id,
            order_number=payload.order_number,
            request_text=payload.request_text,
            failure_node=payload.failure_node,
        )
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return jsonable_encoder(created)


@app.get("/returns/{run_id}")
async def return_status(run_id: UUID, request: Request):
    snapshot = await asyncio.to_thread(
        load_run_snapshot,
        request.app.state.connection_url,
        run_id,
    )
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Return workflow was not found")
    return jsonable_encoder(snapshot)


@app.post("/returns/{run_id}/manager-decision", status_code=status.HTTP_202_ACCEPTED)
async def manager_decision(
    run_id: UUID,
    payload: ManagerDecisionRequest,
    request: Request,
):
    try:
        recorded = await asyncio.to_thread(
            record_manager_decision,
            request.app.state.connection_url,
            run_id=run_id,
            decision=payload.decision,
            decided_by=payload.decided_by,
            decision_note=payload.decision_note,
        )
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return jsonable_encoder(recorded)


@app.post("/returns/{run_id}/resume", status_code=status.HTTP_202_ACCEPTED)
async def resume_after_injected_failure(run_id: UUID, request: Request):
    try:
        resumed = await asyncio.to_thread(
            request_recovery_resume,
            request.app.state.connection_url,
            run_id=run_id,
        )
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return jsonable_encoder(resumed)


@app.get("/returns/{run_id}/inspection-sql")
async def run_inspection_sql(run_id: UUID, request: Request):
    snapshot = await asyncio.to_thread(
        load_run_snapshot,
        request.app.state.connection_url,
        run_id,
    )
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Return workflow was not found")
    return {"run_id": str(run_id), "sql": render_run_inspection_sql(run_id)}


@app.delete("/returns/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
async def reset_return_demo(run_id: UUID, request: Request):
    try:
        thread_id = await asyncio.to_thread(
            reset_demo_run,
            request.app.state.connection_url,
            run_id,
        )
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if thread_id is None:
        raise HTTPException(status_code=404, detail="Synthetic ReturnFlow run was not found")

    def delete_checkpoint() -> None:
        with CockroachDBSaver.from_conn_string(
            request.app.state.connection_url
        ) as saver:
            saver.delete_thread(thread_id)

    await asyncio.to_thread(delete_checkpoint)
    return None
