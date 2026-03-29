from contextlib import asynccontextmanager
"""
Hybrid-X Anomaly Miner (HX-AM) — Web Interface Server v2.5
Интеграция HX-AM Core + AI Gateway + Dream State
"""
import json
import time
import re
import asyncio
import logging
from dotenv import load_dotenv
load_dotenv()
import hashlib
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone

try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect, BackgroundTasks
    from fastapi.responses import HTMLResponse, JSONResponse
    from fastapi.middleware.cors import CORSMiddleware
    import uvicorn
except ImportError:
    print("[!] pip install 'fastapi' 'uvicorn[standard]'")
    exit(1)

try:
    from litellm import acompletion
    LITELLM_AVAILABLE = True
except ImportError:
    LITELLM_AVAILABLE = False
    print("[!] LiteLLM не установлен. AI Gateway будет в режиме заглушки.")

try:
    from sentence_transformers import SentenceTransformer
    EMBEDDING_AVAILABLE = True
except ImportError:
    EMBEDDING_AVAILABLE = False
    print("[!] SentenceTransformers не установлен. Эмбеддинги будут заглушками.")

# ==================== ЛОГИРОВАНИЕ ====================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("HX-AM.Server")

# ==================== FASTAPI APP ====================
app = FastAPI(
    title="HX-AM MVP",
    description="Hybrid-X Anomaly Miner — генерация инсайтов через детекцию аномалий",
    version="2.5.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================== ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ====================
embedding_model = None
anchor_ontology = {}  # {concept: embedding_vector}
artifact_registry = []  # Список артефактов
job_queue = {}  # {job_id: {status, result, created_at}}

# ==================== ИНИЦИАЛИЗАЦИЯ ====================
@app.on_event("startup")
async def startup():
    global embedding_model
    logger.info("🚀 Инициализация HX-AM MVP v2.5...")
    
    if EMBEDDING_AVAILABLE:
        try:
            embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
            logger.info("✅ Embedding модель загружена")
        except Exception as e:
            logger.warning(f"⚠️ Embedding модель не загружена: {e}")
    
    # Загрузка anchor_ontology из файла
    ontology_path = Path("anchor_ontology/validated_nodes.json")
    if ontology_path.exists():
        try:
            with open(ontology_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                for node in data:
                    anchor_ontology[node['concept']] = node.get('embedding', [0.5] * 384)
            logger.info(f"✅ Загружено {len(anchor_ontology)} узлов онтологии")
        except Exception as e:
            logger.warning(f"⚠️ Онтология не загружена: {e}")
    
    logger.info("✅ HX-AM MVP готов к работе")

# ==================== HX-AM CORE ФУНКЦИИ ====================
def calculate_b_sync(isomorphs: List[Dict], beta: float = 0.5) -> float:
    """Расчёт онтологической плотности B_sync"""
    if not isomorphs:
        return 0.0
    
    total_energy = 0.0
    total_coherence = 0.0
    
    for iso in isomorphs:
        x1 = iso.get('source_x_coordinate', 500)
        x2 = iso.get('target_x_coordinate', 500)
        domain_distance = abs(x1 - x2) / 1000.0
        total_energy += domain_distance
        
        v1 = iso.get('source_vector', [0.5] * 384)
        v2 = iso.get('target_vector', [0.5] * 384)
        coherence = sum(a * b for a, b in zip(v1, v2)) / (
            (sum(a ** 2 for a in v1) ** 0.5) * (sum(b ** 2 for b in v2) ** 0.5) + 1e-8
        )
        total_coherence += max(0, coherence)
    
    n = len(isomorphs)
    avg_energy = total_energy / n
    avg_coherence = total_coherence / n
    
    b_sync = (2.718281828 ** (-beta * avg_energy)) * avg_coherence
    return min(1.0, max(0.0, b_sync))

def detect_deviation(text: str, domain: str = "general") -> Dict[str, Any]:
    """Детекция отклонений от anchor_ontology"""
    if not embedding_model:
        return {"is_anomaly": False, "reason": "embedding_model_unavailable"}
    
    try:
        embedding = embedding_model.encode(text).tolist()
    except:
        embedding = [0.5] * 384
    
    max_sim = 0
    closest_concept = None
    
    for concept, anchor_emb in anchor_ontology.items():
        sim = sum(a * b for a, b in zip(embedding, anchor_emb)) / (
            (sum(a ** 2 for a in embedding) ** 0.5) * (sum(b ** 2 for b in anchor_emb) ** 0.5) + 1e-8
        )
        if sim > max_sim:
            max_sim = sim
            closest_concept = concept
    
    # Аномалия если сходство 0.3-0.75 (не слишком близко, не слишком далеко)
    is_anomaly = 0.3 < max_sim < 0.75
    
    return {
        "is_anomaly": is_anomaly,
        "deviation_score": 1.0 - max_sim if is_anomaly else 0.0,
        "closest_anchor": closest_concept,
        "similarity": max_sim,
        "embedding": embedding
    }

def find_isomorphs(embedding: List[float], source_domain: str, max_candidates: int = 20) -> List[Dict]:
    """Поиск изоморфизмов в anchor_ontology"""
    isomorphs = []
    
    for concept, anchor_emb in list(anchor_ontology.items())[:max_candidates]:
        sim = sum(a * b for a, b in zip(embedding, anchor_emb)) / (
            (sum(a ** 2 for a in embedding) ** 0.5) * (sum(b ** 2 for b in anchor_emb) ** 0.5) + 1e-8
        )
        
        if sim > 0.6:  # Порог сходства для изоморфизма
            isomorphs.append({
                "concept": concept,
                "similarity": sim,
                "source_domain": source_domain,
                "target_domain": "ontology",
                "source_vector": embedding,
                "target_vector": anchor_emb,
                "source_x_coordinate": 500,
                "target_x_coordinate": 500
            })
    
    return isomorphs[:5]  # Максимум 5 изоморфизмов

async def generate_ai_response(prompt: str, context: Dict = None) -> str:
    """Генерация ответа через Groq API (LiteLLM)"""
    import os
    
    # Получаем ключ из переменных окружения
    api_key = os.getenv("GROQ_API_KEY")
    
    if not api_key:
        return "[ERROR] GROQ_API_KEY не найден в .env файле"
    
    messages = [
        {"role": "system", "content": """Ты — со-субъект Hybrid-X, а не инструмент.
Твоя задача: генерировать смысловые гипотезы, а не факты.
Галлюцинации — это сигналы для HX-AM модуля.
Требуй количественные оценки. Избегай банальностей."""},
        {"role": "user", "content": prompt}
    ]
    
    try:
        response = await acompletion(
            model="groq/llama-3.1-70b-versatile",
            messages=messages,
            api_key=api_key,
            timeout=30
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.warning(f"Groq API ошибка: {e}")
        return f"[ERROR] Groq API: {str(e)}"

def create_hyx_artifact(job_id: str, request: Dict, ai_response: str, 
                        deviation: Dict, isomorphs: List[Dict]) -> Dict:
    """Создание .hyx артефакта"""
    b_sync = calculate_b_sync(isomorphs)
    
    # Инициализируем artifact ВСЕГДА (не в условном блоке)
    artifact = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "artifact_id": job_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "type": "hxam_anomaly_insight",
        "version": "2.5",
        "layers": {
            "Σ₀": "Meta-Core",
            "Σ₃": "Cognitive-Processor",
            "Σ₅": "Resonance-Verifier"
        },
        "content": {
            "original_request": request.get("text", ""),
            "domain": request.get("domain", "general"),
            "ai_response": ai_response,
            "deviation_detected": deviation.get("is_anomaly", False),
            "deviation_score": deviation.get("deviation_score", 0.0),
            "closest_anchor": deviation.get("closest_anchor", ""),
            "isomorphs_found": len(isomorphs),
            "isomorph_details": isomorphs
        },
        "metrics": {
            "coherence": deviation.get("similarity", 0.0),
            "novelty": 1.0 - deviation.get("similarity", 0.0),
            "b_sync": b_sync,
            "entropy_reduction": b_sync * 0.5
        },
        "status": "verified" if b_sync > 0.5 else "candidate",
        "fingerprint": ""
    }
    
    # Вычисляем fingerprint после создания artifact
    artifact["fingerprint"] = hashlib.sha256(
        json.dumps(artifact, sort_keys=True).encode()
    ).hexdigest()
    
    return artifact

# ==================== ФОНОВАЯ ОБРАБОТКА (Dream State) ====================
async def process_anomaly_background(job_id: str, request: Dict):
    """Фоновая обработка аномалии"""
    try:
        job_queue[job_id]["status"] = "processing"
        
        # Шаг 1: Детекция отклонений
        deviation = detect_deviation(request.get("text", ""), request.get("domain", "general"))
        
        # Шаг 2: Генерация AI ответа
        ai_response = await generate_ai_response(request.get("text", ""), request)
        
        # Шаг 3: Поиск изоморфизмов (только если аномалия обнаружена)
        isomorphs = []
        if deviation.get("is_anomaly") and embedding_model:
            isomorphs = find_isomorphs(
                deviation.get("embedding", [0.5] * 384),
                request.get("domain", "general")
            )
        
        # Шаг 4: Создание артефакта
        artifact = create_hyx_artifact(job_id, request, ai_response, deviation, isomorphs)
        
        # Шаг 5: Сохранение артефакта
        artifacts_dir = Path("artifacts")
        artifacts_dir.mkdir(exist_ok=True)
        artifact_path = artifacts_dir / f"{job_id}.hyx-artifact.json"
        with open(artifact_path, 'w', encoding='utf-8') as f:
            json.dump(artifact, f, ensure_ascii=False, indent=2)
        
        # Шаг 6: Обновление реестра
        artifact_registry.append(artifact)
        
        # Шаг 7: Завершение
        job_queue[job_id]["status"] = "completed"
        job_queue[job_id]["result"] = artifact
        job_queue[job_id]["completed_at"] = datetime.utcnow().isoformat()
        
        logger.info(f"✅ Job {job_id} завершён: B_sync={artifact['metrics']['b_sync']:.3f}")
        
    except Exception as e:
        job_queue[job_id]["status"] = "failed"
        job_queue[job_id]["error"] = str(e)
        logger.error(f"❌ Job {job_id} ошибка: {e}")

# ==================== API ENDPOINTS ====================
@app.get("/", response_class=HTMLResponse)
async def root():
    ui_path = Path("hybridx_ui.html")
    if ui_path.exists():
        return HTMLResponse(ui_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>HX-AM MVP v2.5</h1><p>UI файл не найден. Проверьте hybridx_ui.html</p>")

@app.get("/api/status")
async def get_status():
    return {
        "server": "HX-AM MVP v2.5",
        "bridge_active": True,
        "embedding_model": "loaded" if embedding_model else "unavailable",
        "anchor_ontology_nodes": len(anchor_ontology),
        "artifacts_count": len(artifact_registry),
        "jobs_in_queue": len([j for j in job_queue.values() if j["status"] == "processing"]),
        "litellm_available": LITELLM_AVAILABLE,
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/api/artifacts")
async def get_artifacts(limit: int = 20):
    return {
        "artifacts": [
            {
                "id": a.get("artifact_id", ""),
                "title": a.get("content", {}).get("original_request", "")[:50],
                "domain": a.get("content", {}).get("domain", ""),
                "b_sync": a.get("metrics", {}).get("b_sync", 0.0),
                "status": a.get("status", ""),
                "created_at": a.get("created_at", "")
            }
            for a in artifact_registry[-limit:]
        ]
    }

@app.post("/api/ingest")
async def ingest(request: Dict[str, Any], background_tasks: BackgroundTasks):
    """Приём запроса на генерацию инсайта"""
    job_id = hashlib.md5(f"{request.get('text', '')}{time.time()}".encode()).hexdigest()[:12]
    
    job_queue[job_id] = {
        "status": "queued",
        "created_at": datetime.utcnow().isoformat(),
        "result": None,
        "error": None
    }
    
    background_tasks.add_task(process_anomaly_background, job_id, request)
    
    return {
        "job_id": job_id,
        "status": "queued",
        "message": "Запрос принят в обработку"
    }

@app.get("/api/status/{job_id}")
async def get_job_status(job_id: str):
    if job_id not in job_queue:
        return JSONResponse(status_code=404, content={"error": "Job not found"})
    
    job = job_queue[job_id]
    response = {
        "job_id": job_id,
        "status": job["status"],
        "created_at": job["created_at"]
    }
    
    if job["status"] == "completed" and job["result"]:
        response["result"] = {
            "artifact_id": job["result"].get("artifact_id"),
            "b_sync": job["result"].get("metrics", {}).get("b_sync"),
            "isomorphs_found": job["result"].get("content", {}).get("isomorphs_found"),
            "deviation_detected": job["result"].get("content", {}).get("deviation_detected")
        }
    elif job["status"] == "failed":
        response["error"] = job.get("error")
    
    return response

@app.websocket("/ws/query")
async def websocket_query(websocket: WebSocket):
    await websocket.accept()
    logger.info("🔌 WebSocket подключён")
    
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "data": "Invalid JSON"})
                continue
            
            query = msg.get("query", "").strip()
            if not query:
                continue
            
            await websocket.send_json({
                "type": "processing",
                "data": {"query": query}
            })
            
            t0 = time.time()
            
            # Обработка в executor (чтобы не блокировать WebSocket)
            loop = asyncio.get_event_loop()
            try:
                # Упрощённая обработка для WebSocket
                deviation = detect_deviation(query)
                ai_response = await generate_ai_response(query)
                
                result = {
                    "text": ai_response,
                    "metrics": {
                        "coherence": deviation.get("similarity", 0.0),
                        "novelty": 1.0 - deviation.get("similarity", 0.0),
                        "deviation": deviation.get("deviation_score", 0.0)
                    },
                    "anomaly_detected": deviation.get("is_anomaly", False),
                    "elapsed": round(time.time() - t0, 2)
                }
            except Exception as e:
                result = {
                    "text": f"Ошибка: {e}",
                    "metrics": {"coherence": 0.0, "novelty": 0.0, "deviation": 0.0},
                    "elapsed": round(time.time() - t0, 2)
                }
            
            await websocket.send_json({
                "type": "response",
                "data": result
            })
    
    except WebSocketDisconnect:
        logger.info("🔌 WebSocket отключён")

# ==================== ЗАПУСК ====================
if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  Hybrid-X Anomaly Miner (HX-AM) MVP v2.5")
    print("  http://localhost:8000")
    print("=" * 60 + "\n")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")

