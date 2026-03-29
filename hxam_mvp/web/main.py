from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
import time
import hashlib

app = FastAPI(
    title="HX-AM MVP",
    description="Hybrid-X Anomaly Miner — генерация инсайтов через детекцию аномалий",
    version="0.1.0"
)

class InsightRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Текст запроса")
    domain: str = Field(default="general", description="Домен: physics, biology, ontology...")
    context: Optional[Dict[str, Any]] = None

class JobResponse(BaseModel):
    job_id: str
    status: str = "queued"
    message: str

@app.post("/ingest", response_model=JobResponse)
async def ingest(request: InsightRequest, background: BackgroundTasks):
    """Приём запроса на генерацию инсайта"""
    job_id = hashlib.md5(f"{request.text}{time.time()}".encode()).hexdigest()[:12]
    
    # Ставим в фоновую обработку
    background.add_task(process_anomaly, job_id, request)
    
    return JobResponse(job_id=job_id, message="Запрос принят в обработку")

async def process_anomaly(job_id: str, request: InsightRequest):
    """Фоновая обработка аномалии (заглушка для MVP)"""
    # Здесь будет логика Σ₅-Refine
    time.sleep(2)  # Имитация работы
    print(f"✅ Job {job_id} processed: {request.text[:50]}...")

@app.get("/status/{job_id}")
async def get_status(job_id: str):
    """Статус обработки"""
    # В реальном проекте — проверка Redis/DB
    return {"job_id": job_id, "status": "completed", "result": "artifact_generated"}

@app.get("/")
async def root():
    return {"message": "HX-AM MVP ready", "docs": "/docs"}
