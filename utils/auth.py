"""
Authentication utilities for the API.
"""

import os
import logging
from functools import wraps
from flask import request, jsonify

logger = logging.getLogger(__name__)

# API key for authentication (set in Railway environment variables)
APP_API_KEY = os.environ.get('APP_API_KEY')


def require_api_key(f):
    """Decorator to require API key for protected endpoints."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not APP_API_KEY:
            # If no API key configured, allow requests (for backwards compatibility)
            logger.warning("APP_API_KEY not configured - endpoint is unprotected")
            return f(*args, **kwargs)

        provided_key = request.headers.get('X-API-Key')
        if not provided_key or provided_key != APP_API_KEY:
            logger.warning(f"Unauthorized request attempt from {request.remote_addr}")
            return jsonify({
                'success': False,
                'error': 'Unauthorized - invalid or missing API key'
            }), 401
        return f(*args, **kwargs)
    return decorated
