"""
AI proxy routes.
Proxies requests to Gemini API, keeping API keys secure on server.
"""

import logging
from flask import Blueprint, jsonify, request

from utils.auth import require_api_key
from services.ai_service import generate_completion, AIServiceError

logger = logging.getLogger(__name__)

ai_bp = Blueprint('ai', __name__)


@ai_bp.route('/ai/complete', methods=['POST'])
@require_api_key
def complete():
    """
    Generate AI completion.

    Request body:
    {
        "prompt": "Your prompt here",
        "max_tokens": 2048,      // optional, default 2048
        "temperature": 0.7       // optional, default 0.7
    }

    Response:
    {
        "success": true,
        "text": "Generated response..."
    }
    """
    data = request.get_json()

    if not data or 'prompt' not in data:
        return jsonify({
            'success': False,
            'error': 'Missing "prompt" in request body'
        }), 400

    prompt = data['prompt']
    max_tokens = data.get('max_tokens', 2048)
    temperature = data.get('temperature', 0.7)

    # Validate parameters
    if not isinstance(prompt, str) or len(prompt) == 0:
        return jsonify({
            'success': False,
            'error': 'Invalid prompt'
        }), 400

    if not isinstance(max_tokens, int) or max_tokens < 1 or max_tokens > 8192:
        return jsonify({
            'success': False,
            'error': 'max_tokens must be between 1 and 8192'
        }), 400

    if not isinstance(temperature, (int, float)) or temperature < 0 or temperature > 2:
        return jsonify({
            'success': False,
            'error': 'temperature must be between 0 and 2'
        }), 400

    try:
        logger.info(f"AI completion request (prompt_len={len(prompt)}, max_tokens={max_tokens})")
        text = generate_completion(prompt, max_tokens, temperature)

        return jsonify({
            'success': True,
            'text': text
        }), 200

    except AIServiceError as e:
        logger.error(f"AI service error: {e.message}")
        return jsonify({
            'success': False,
            'error': e.message
        }), e.status_code

    except Exception as e:
        logger.error(f"Unexpected error in AI completion: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'An unexpected error occurred'
        }), 500
