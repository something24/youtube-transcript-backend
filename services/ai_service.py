"""
AI service for proxying requests to Gemini API.
Keeps API keys secure on the server side.
"""

import os
import logging
import requests

logger = logging.getLogger(__name__)

# Gemini API configuration
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
GEMINI_MODEL = "gemini-2.0-flash"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"


class AIServiceError(Exception):
    """Custom exception for AI service errors."""
    def __init__(self, message: str, status_code: int = 500):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)


def generate_completion(prompt: str, max_tokens: int = 2048, temperature: float = 0.7) -> str:
    """
    Generate text completion using Gemini API.

    Args:
        prompt: The input prompt
        max_tokens: Maximum tokens in response
        temperature: Creativity level (0.0-1.0)

    Returns:
        Generated text response

    Raises:
        AIServiceError: If API call fails
    """
    if not GEMINI_API_KEY:
        logger.error("GEMINI_API_KEY not configured")
        raise AIServiceError("AI service not configured", 503)

    url = f"{GEMINI_BASE_URL}/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"

    payload = {
        "contents": [
            {
                "parts": [{"text": prompt}],
                "role": "user"
            }
        ],
        "generationConfig": {
            "maxOutputTokens": max_tokens,
            "temperature": temperature
        }
    }

    headers = {
        "Content-Type": "application/json"
    }

    try:
        logger.info(f"Calling Gemini API (max_tokens={max_tokens}, temp={temperature})")
        response = requests.post(url, json=payload, headers=headers, timeout=60)

        if response.status_code != 200:
            error_data = response.json() if response.content else {}
            error_msg = error_data.get('error', {}).get('message', 'Unknown error')
            logger.error(f"Gemini API error: {response.status_code} - {error_msg}")
            raise AIServiceError(f"AI API error: {error_msg}", response.status_code)

        data = response.json()

        # Extract text from response
        candidates = data.get('candidates', [])
        if not candidates:
            raise AIServiceError("No response generated", 500)

        content = candidates[0].get('content', {})
        parts = content.get('parts', [])
        if not parts:
            raise AIServiceError("Empty response from AI", 500)

        text = parts[0].get('text', '')
        logger.info(f"Gemini response received ({len(text)} chars)")

        return text

    except requests.exceptions.Timeout:
        logger.error("Gemini API timeout")
        raise AIServiceError("AI service timeout", 504)
    except requests.exceptions.RequestException as e:
        logger.error(f"Gemini API request failed: {e}")
        raise AIServiceError(f"AI service unavailable: {str(e)}", 503)
