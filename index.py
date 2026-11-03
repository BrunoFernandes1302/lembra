"""Ponto de entrada na Vercel: ela procura um `app` FastAPI em index.py na raiz.

O código do Lembra fica em src/lembra; aqui só o deixamos "importável" e apontamos a pasta
do app (web/), que a Vercel promove para a CDN (servido rápido, sem gastar a função Python).
"""

import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ / "src"))
os.environ.setdefault("LEMBRA_WEB_DIR", str(RAIZ / "web"))

from lembra.api import app  # noqa: E402,F401
