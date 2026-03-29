#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HX-AM MVP — Точка входа
Запуск: python -m hxam_mvp
"""
import sys
from pathlib import Path

# Добавляем корень проекта в path
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from hxam_mvp.web.main import app  # FastAPI app

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("hxam_mvp.web.main:app", host="0.0.0.0", port=8000, reload=True)
