import json
import hashlib
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional

class ChatHistoryManager:
    """Менеджер истории чатов для статистики (исправленная версия)"""
    
    def __init__(self, storage_path: str = "chat_history"):
        # Абсолютный путь к папке истории
        self.storage_path = Path(storage_path).resolve()
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.session_id = self._generate_session_id()
        self.max_entries_per_file = 100
        self.current_entries: List[Dict[str, Any]] = []
        
    def _generate_session_id(self) -> str:
        """Генерация уникального ID сессии"""
        return f"sess_{hashlib.md5(f'{time.time()}'.encode()).hexdigest()[:8]}"

    def log_query(self, query: Dict[str, Any], response: Dict[str, Any], response_time_ms: float, artifact_filename: Optional[str] = None):
        """Логирование запроса-ответа (сохраняет сразу в файл)"""
        entry = {
            "session_id": self.session_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "query_text": str(query.get("text", ""))[:500],
            "detected_domain": response.get("detected_domain", "unknown"),
            "detected_x_coordinate": response.get("detected_x_coordinate", 500),
            "status_type": response.get("status", {}).get("type", "unknown"),
            "b_sync": response.get("metrics", {}).get("b_sync", 0.0),
            "artifact_saved": response.get("save_artifact", False),
            "artifact_filename": artifact_filename,
            "response_time_ms": round(response_time_ms, 2),
            "error": response.get("error")
        }
        
        # Сохраняем СРАЗУ в файл (jsonl формат — одна запись на строку)
        filepath = self.storage_path / f"history_{self.session_id}.jsonl"
        try:
            with open(filepath, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"[!] Error saving history: {e}")
    
    def get_statistics(self, limit: int = 1000) -> Dict[str, Any]:
        """Получение статистики по истории"""
        all_entries: List[Dict[str, Any]] = []
        
        # Читаем ВСЕ файлы history_*.jsonl из папки
        for filepath in self.storage_path.glob("history_*.jsonl"):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            all_entries.append(json.loads(line))
            except Exception as e:
                print(f"[!] Error reading {filepath}: {e}")
                continue
        
        # Сортировка по времени (новые первые)
        all_entries.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        all_entries = all_entries[:limit]
        
        if not all_entries:
            return {"total_queries": 0, "artifacts_saved": 0, "errors": 0}
        
        # Расчёт статистики
        total = len(all_entries)
        artifacts = sum(1 for e in all_entries if e.get("artifact_saved"))
        errors = sum(1 for e in all_entries if e.get("error"))
        avg_b_sync = sum(e.get("b_sync", 0) for e in all_entries) / total
        avg_response_time = sum(e.get("response_time_ms", 0) for e in all_entries) / total
        
        # Распределение по типам статуса
        status_dist: Dict[str, int] = {}
        for e in all_entries:
            status = e.get("status_type", "unknown")
            status_dist[status] = status_dist.get(status, 0) + 1
        
        # Распределение по доменам
        domain_dist: Dict[str, int] = {}
        for e in all_entries:
            domain = e.get("detected_domain", "unknown")
            domain_dist[domain] = domain_dist.get(domain, 0) + 1
        
        return {
            "total_queries": total,
            "artifacts_saved": artifacts,
            "errors": errors,
            "avg_b_sync": round(avg_b_sync, 3),
            "avg_response_time_ms": round(avg_response_time, 2),
            "status_distribution": status_dist,
            "domain_distribution": domain_dist,
            "unique_sessions": len(set(e.get("session_id") for e in all_entries))
        }

    def get_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Получение последних записей истории"""
        all_entries: List[Dict[str, Any]] = []
        
        for filepath in self.storage_path.glob("history_*.jsonl"):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            all_entries.append(json.loads(line))
            except:
                continue
        
        all_entries.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return all_entries[:limit]
