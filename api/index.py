import os
import sys

CURRENT_DIR = os.path.dirname(__file__)
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
PY_APP_DIR = os.path.join(PROJECT_ROOT, "app")
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
if PY_APP_DIR not in sys.path:
    sys.path.insert(0, PY_APP_DIR)

from app.main import app  # ASGI app for Vercel
