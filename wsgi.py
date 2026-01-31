"""
WSGI entry point for gunicorn.
Sets up Python path before importing the Flask app.
"""

import os
import sys

# Ensure the app directory is in Python path
app_dir = os.path.dirname(os.path.abspath(__file__))
if app_dir not in sys.path:
    sys.path.insert(0, app_dir)

from app import app

if __name__ == "__main__":
    app.run()
