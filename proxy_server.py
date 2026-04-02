"""
HX-AM MVP — Thin AI Proxy v3.4
На основе документов Hybrid-X: Node Net, Fase 4, Архив артефактов, B_sync формула
Режим: AI-Proxy (Groq/llama-3.3-70b-versatile)
"""
import os
import json
import hashlib
import logging
import asyncio
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any

from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from pydantic import BaseModel, Field, ValidationError
from dotenv import load_dotenv
from llm_client import GroqClient
def extract_json_from_text(text: str) -> str:
    """Извлекает JSON из текста, удаляя преамбулы и посторонние символы."""
    import re
    # Убираем маркеры кода
    text = re.sub(r'`json\s*|\s*`', '', text)
    # Ищем первую открывающую скобку { или [
    start = -1
    for i, ch in enumerate(text):
        if ch in '{[':
            start = i
            break
    if start == -1:
        return ''
    # Подсчёт вложенности
    stack = []
    end = -1
    for i in range(start, len(text)):
        ch = text[i]
        if ch in '{[':
            stack.append(ch)
        elif ch == '}' and stack and stack[-1] == '{':
            stack.pop()
            if not stack:
                end = i
                break
        elif ch == ']' and stack and stack[-1] == '[':
            stack.pop()
            if not stack:
                end = i
                break
    if end == -1:
        return ''
    json_str = text[start:end+1]
    # Удаляем trailing commas перед } или ]
    json_str = re.sub(r',\s*}', '}', json_str)
    json_str = re.sub(r',\s*]', ']', json_str)
    return json_str

try:
    from chat_history_class import ChatHistoryManager
    chat_history = ChatHistoryManager(storage_path="chat_history")
except ImportError:
    class DummyCH:
        def log_query(self, *a, **k): pass
        def get_statistics(self, limit=1000): return {"total_queries": 0, "error": "not_ready"}
        def get_history(self, limit=20): return []
    chat_history = DummyCH()

try:
    from litellm import acompletion
    LITELLM_OK = True
except ImportError:
    LITELLM_OK = False
    print("[!] pip install litellm")

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("HX-AM.Proxy")

app = FastAPI(title="HX-AM Proxy", version="3.4")

# ═══════════════════════════════════════════════════════════════════════════
# СИСТЕМНЫЙ ПРОМПТ v3.4 (ФИНАЛЬНЫЙ)
# ═══════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════
# СИСТЕМНЫЙ ПРОМПТ — загружается из system_prompt.txt
# ═══════════════════════════════════════════════════════════════════════════

def load_system_prompt() -> str:
    """Загружает промпт из system_prompt.txt. Если файл не найден, выбрасывает исключение."""
    prompt_file = Path(__file__).parent / "system_prompt.txt"
    if not prompt_file.exists():
        raise FileNotFoundError(
            "system_prompt.txt not found. Please create it in the project root."
        )
    return prompt_file.read_text(encoding="utf-8")

SYSTEM_PROMPT = load_system_prompt()

# ═══════════════════════════════════════════════════════════════════════════
# МОДЕЛИ ДАННЫХ
# ═══════════════════════════════════════════════════════════════════════════

class QueryRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    domain: Optional[str] = Field(default="general")
    x_coordinate: Optional[float] = Field(default=500.0, ge=0, le=1000)

class QueryResponse(BaseModel):
    job_id: str
    status: str
    result: Optional[Dict[str, Any]] = None
    artifact_saved: Optional[str] = None
    error: Optional[str] = None

class AIResponseModel(BaseModel):
    status: str
    analysis: Dict[str, Any]
    metrics: Dict[str, Any]
    response_text: str
    save_artifact: bool

# ═══════════════════════════════════════════════════════════════════════════
# ЛОГИКА
# ═══════════════════════════════════════════════════════════════════════════

def generate_artifact_path(job_id: str, content: Dict[str, Any]) -> str:
    """Сохранить ответ как .hyx артефакт"""
    artifacts_dir = Path("artifacts")
    artifacts_dir.mkdir(exist_ok=True)
    
    artifact = {
        "id": job_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "type": "hxam_insight",
        "version": "3.4",
        "content": content,
        "metrics": content.get("metrics", {}),
        "fingerprint": hashlib.sha256(
            json.dumps(content, sort_keys=True).encode()
        ).hexdigest()[:16]
    }
    
    filepath = artifacts_dir / f"{job_id}.hyx.json"
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(artifact, f, ensure_ascii=False, indent=2)
    
    return str(filepath)

async def process_query(request: QueryRequest, max_retries: int = 3) -> Dict[str, Any]:
    """Отправить запрос в AI с системным промтом"""
    client = GroqClient()
    if not client.available:
        return {"error": "LiteLLM not installed. Run: pip install litellm"}

    user_prompt = f"""Домен: {request.domain}
Уровень масштаба (X): {request.x_coordinate}
Запрос: {request.text}

Проанализируй по принципам HX-AM и верни ТОЛЬКО JSON."""

    for attempt in range(max_retries):
        try:
            content = await client.complete(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ]
            )

            json_str = extract_json_from_text(content)
            if not json_str:
                raise ValueError("No JSON found in response")

            try:
                result = json.loads(json_str)
            except json.JSONDecodeError:
                import re
                cleaned = re.sub(r'[\x00-\x1f\x7f]', '', json_str)
                result = json.loads(cleaned)

            required_fields = ["status", "analysis", "metrics", "response_text", "save_artifact"]
            for field in required_fields:
                if field not in result:
                    raise ValueError(f"Missing required field: {field}")

            b_sync = result.get("metrics", {}).get("b_sync", 0.0)
            if b_sync > 0.50 and not result.get("save_artifact"):
                result["save_artifact"] = True
                logger.info(f"Auto-corrected save_artifact to True (b_sync={b_sync:.2f})")

            return result
        except Exception as e:
            logger.error(f"AI error (attempt {attempt+1}/{max_retries}): {e}")
            error_str = str(e).lower()
            if "ratelimiterror" in error_str or "rate_limit" in error_str or "rate limit" in error_str:
                wait_time = 20 * (attempt + 1)
                logger.warning(f"Rate limit hit. Waiting {wait_time}s before retry...")
                await asyncio.sleep(wait_time)
            elif attempt == max_retries - 1:
                return {"error": f"AI request failed: {str(e)}"}
            else:
                await asyncio.sleep(2 ** attempt)
    
    return {"error": "Max retries exceeded"}

# ═══════════════════════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
async def root():
    """Отдаём красивый интерфейс из index.html"""
    try:
        with open("index.html", "r", encoding="utf-8") as f:
            html_content = f.read()
        return HTMLResponse(content=html_content)
    except FileNotFoundError:
        # fallback на встроенный минимальный интерфейс
        return HTMLResponse(content="""
        <!DOCTYPE html>
        <html lang="ru">
        <head>
            <meta charset="UTF-8">
            <title>HX-AM Proxy v3.4</title>
            <style>
                body { font-family: monospace; background: #0f172a; color: #e2e8f0; padding: 2rem; }
                textarea { width: 100%; background: #1e293b; color: #fff; }
                button { background: #6366f1; color: #fff; padding: 0.5rem 1rem; margin-top: 1rem; }
                .result { background: #1e293b; padding: 1rem; margin-top: 1rem; }
            </style>
        </head>
        <body>
            <h1>🔮 HX-AM Proxy v3.4</h1>
            <p>Файл index.html не найден. Используйте встроенную форму.</p>
            <form id="queryForm">
                <textarea id="queryText" rows="6" cols="80" placeholder="Введите запрос..."></textarea><br>
                <button type="submit">Отправить</button>
            </form>
            <div id="result"></div>
            <script>
                document.getElementById('queryForm').onsubmit = async (e) => {
                    e.preventDefault();
                    const text = document.getElementById('queryText').value;
                    const res = await fetch('/api/query', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({text, domain: 'auto', x_coordinate: 500})
                    });
                    const data = await res.json();
                    const resultDiv = document.getElementById('result');
                    if (data.error) resultDiv.innerHTML = '<div class="result">Ошибка: ' + data.error + '</div>';
                    else resultDiv.innerHTML = '<div class="result"><pre>' + JSON.stringify(data.result, null, 2) + '</pre></div>';
                };
            </script>
        </body>
        </html>
        """)

@app.post("/api/query", response_model=QueryResponse)
async def api_query(request: QueryRequest):
    """Основной эндпоинт: запрос → AI → ответ → авто-сохранение артефакта"""
    start_time = time.time()
    
    job_id = hashlib.md5(
        f"{request.text}{datetime.now().isoformat()}".encode()
    ).hexdigest()[:12]
    
    try:
        result = await process_query(request)
        
        if "error" in result:
            # Создаём корректный fallback-ответ для истории, чтобы избежать ошибок в статистике
            fallback_response = {
                "detected_domain": "error",
                "detected_x_coordinate": 500,
                "status": {"type": "error"},
                "metrics": {"b_sync": 0.0},
                "save_artifact": False,
                "error": result["error"]
            }
            if chat_history is not None:
                chat_history.log_query(
                    query={"text": request.text, "domain": request.domain},
                    response=fallback_response,
                    response_time_ms=(time.time() - start_time) * 1000
                )
            return QueryResponse(
                job_id=job_id,
                status="failed",
                error=result["error"]
            )
        
        artifact_path = None
        if result.get("save_artifact", False):
            artifact_path = generate_artifact_path(job_id, result)
            logger.info(f"Артефакт сохранён: {artifact_path}")
        
        # Логирование в историю чатов (только для успешных ответов)
        if chat_history is not None:
            chat_history.log_query(
                query={"text": request.text, "domain": request.domain},
                response=result,
                response_time_ms=(time.time() - start_time) * 1000
            )
        
        return QueryResponse(
            job_id=job_id,
            status="completed",
            result=result,
            artifact_saved=artifact_path
        )
        
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        # Логируем ошибку в историю
        if chat_history is not None:
            chat_history.log_query(
                query={"text": request.text, "domain": request.domain},
                response={"error": str(e), "detected_domain": "error", "metrics": {"b_sync": 0.0}},
                response_time_ms=(time.time() - start_time) * 1000
            )
        return QueryResponse(
            job_id=job_id,
            status="failed",
            error=str(e)
        )

@app.get("/api/status")
async def status():
    """Проверка работоспособности"""
    return {
        "server": "HX-AM Proxy v3.4",
        "litellm": LITELLM_OK,
        "groq_key": "set" if os.getenv("GROQ_API_KEY") else "missing",
        "artifacts_dir": str(Path("artifacts").absolute())
    }

@app.get("/api/artifacts")
async def list_artifacts(limit: int = 20):
    """Список последних артефактов"""
    artifacts_dir = Path("artifacts")
    if not artifacts_dir.exists():
        return {"artifacts": []}
    
    files = sorted(artifacts_dir.glob("*.hyx.json"), key=lambda f: f.stat().st_mtime, reverse=True)
    artifacts = []
    
    for f in files[:limit]:
        try:
            with open(f, "r", encoding="utf-8") as file:
                data = json.load(file)
                artifacts.append({
                    "id": data.get("id"),
                    "created_at": data.get("created_at"),
                    "b_sync": data.get("metrics", {}).get("b_sync"),
                    "type": data.get("content", {}).get("status", {}).get("type"),
                    "filepath": str(f)
                })
        except Exception as e:
            logger.warning(f"Error reading artifact {f}: {e}")
    
    return {"artifacts": artifacts}

@app.get("/api/statistics")
async def get_statistics(limit: int = 1000):
    """Получение статистики по истории чатов"""
    if chat_history is None:
        return {"error": "ChatHistoryManager not initialized"}
    stats = chat_history.get_statistics(limit=limit)
    return stats

@app.get("/api/history")
async def get_history(limit: int = 20):
    """Получение последних записей истории чатов"""
    if chat_history is None:
        return {"error": "ChatHistoryManager not initialized"}
    history = chat_history.get_history(limit=limit)
    return {"history": history}

# ═══════════════════════════════════════════════════════════════════════════
# ЗАПУСК
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    print("\n" + "="*60)
    print("  HX-AM Proxy v3.4 — тонкий AI-прокси")
    print("  http://localhost:8000")
    print("="*60 + "\n")
    uvicorn.run(app, host="0.0.0.0", port=8000)



