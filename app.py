"""
YTSummary Backend API

Flask application for:
- YouTube transcript fetching
- AI completion proxy (Gemini)
"""

import os
import re
import logging
import requests
from functools import wraps
from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable,
    RequestBlocked
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)
CORS(app)

# Rate limiting
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["100 per hour", "10 per minute"]
)

# Limit max request body size (100KB for AI prompts)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024

# Environment variables
APP_API_KEY = os.environ.get('APP_API_KEY')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
GEMINI_MODEL = "gemini-2.0-flash"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

# Initialize YouTube transcript API
ytt_api = YouTubeTranscriptApi()


# =============================================================================
# AUTH UTILITIES
# =============================================================================

def require_api_key(f):
    """Decorator to require API key for protected endpoints."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not APP_API_KEY:
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


# =============================================================================
# VALIDATORS
# =============================================================================

def extract_video_id(url):
    """Extract video ID from various YouTube URL formats."""
    patterns = [
        r'(?:youtube\.com/watch\?v=)([a-zA-Z0-9_-]{11})',
        r'(?:youtu\.be/)([a-zA-Z0-9_-]{11})',
        r'(?:youtube\.com/embed/)([a-zA-Z0-9_-]{11})',
        r'(?:youtube\.com/v/)([a-zA-Z0-9_-]{11})',
        r'(?:youtube\.com/shorts/)([a-zA-Z0-9_-]{11})',
    ]

    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)

    if re.match(r'^[a-zA-Z0-9_-]{11}$', url):
        return url

    return None


def is_valid_video_id(video_id):
    """Check if a string is a valid YouTube video ID."""
    return bool(re.match(r'^[a-zA-Z0-9_-]{11}$', video_id))


# =============================================================================
# TRANSCRIPT SERVICE
# =============================================================================

def get_transcript(video_id, include_timestamps=False):
    """Fetch transcript using youtube-transcript-api."""
    logger.info(f"Fetching transcript for video: {video_id}")

    transcript_list = ytt_api.list(video_id)
    transcript = None
    is_generated = False
    language = 'en'

    # First try manually created English transcript
    try:
        transcript = transcript_list.find_manually_created_transcript(['en', 'en-US', 'en-GB'])
        is_generated = False
        language = transcript.language_code
        logger.info(f"Found manual transcript in {language}")
    except NoTranscriptFound:
        pass

    # Fall back to auto-generated English
    if transcript is None:
        try:
            transcript = transcript_list.find_generated_transcript(['en', 'en-US', 'en-GB'])
            is_generated = True
            language = transcript.language_code
            logger.info(f"Found auto-generated transcript in {language}")
        except NoTranscriptFound:
            pass

    # Fall back to any available transcript
    if transcript is None:
        try:
            for t in transcript_list:
                transcript = t
                is_generated = t.is_generated
                language = t.language_code
                logger.info(f"Found transcript in {language}")

                if not language.startswith('en') and t.is_translatable:
                    try:
                        transcript = transcript.translate('en')
                        language = 'en'
                        logger.info("Translated to English")
                    except Exception as te:
                        logger.warning(f"Translation failed: {te}")
                break
        except Exception as e:
            logger.error(f"Error getting fallback transcript: {e}")
            raise Exception(f"No transcript found for video {video_id}")

    if transcript is None:
        raise Exception(f"No transcript available for video {video_id}")

    transcript_data = transcript.fetch()

    if include_timestamps:
        segments = []
        for entry in transcript_data:
            text = re.sub(r'\[.*?\]', '', entry.text).strip()
            if text:
                segments.append({
                    'text': text,
                    'start': entry.start,
                    'duration': entry.duration
                })
        return segments, language, is_generated
    else:
        transcript_text = ' '.join([entry.text for entry in transcript_data])
        transcript_text = re.sub(r'\s+', ' ', transcript_text).strip()
        transcript_text = re.sub(r'\[.*?\]', '', transcript_text)
        return transcript_text, language, is_generated


# =============================================================================
# AI SERVICE
# =============================================================================

class AIServiceError(Exception):
    def __init__(self, message, status_code=500):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)


def generate_completion(prompt, max_tokens=2048, temperature=0.7):
    """Generate text completion using Gemini API."""
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

    try:
        logger.info(f"Calling Gemini API (max_tokens={max_tokens})")
        response = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=60)

        if response.status_code != 200:
            error_data = response.json() if response.content else {}
            error_msg = error_data.get('error', {}).get('message', 'Unknown error')
            logger.error(f"Gemini API error: {response.status_code} - {error_msg}")
            raise AIServiceError(f"AI API error: {error_msg}", response.status_code)

        data = response.json()
        candidates = data.get('candidates', [])
        if not candidates:
            raise AIServiceError("No response generated", 500)

        parts = candidates[0].get('content', {}).get('parts', [])
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


# =============================================================================
# ROUTES - Health
# =============================================================================

@app.route('/')
def home():
    """API info endpoint."""
    return jsonify({
        'status': 'ok',
        'service': 'YTSummary Backend',
        'version': '4.0.0',
        'endpoints': {
            '/health': 'Health check',
            '/transcript/<video_id>': 'Get transcript by video ID',
            '/transcript (POST)': 'Get transcript by URL',
            '/debug/<video_id>': 'List available transcripts',
            '/ai/complete (POST)': 'AI text completion'
        }
    })


@app.route('/health')
def health():
    """Health check for monitoring."""
    return jsonify({'status': 'healthy'}), 200


# =============================================================================
# ROUTES - Transcript
# =============================================================================

@app.route('/transcript/<video_id>', methods=['GET'])
@require_api_key
def get_transcript_endpoint(video_id):
    """Get transcript for a YouTube video."""
    if not is_valid_video_id(video_id):
        return jsonify({
            'success': False,
            'error': 'Invalid video ID format'
        }), 400

    include_timestamps = request.args.get('timestamps', 'false').lower() == 'true'

    try:
        result, language, is_generated = get_transcript(video_id, include_timestamps)

        if not result:
            raise NoTranscriptFound(video_id)

        if include_timestamps:
            logger.info(f"Successfully fetched transcript ({len(result)} segments)")
            return jsonify({
                'success': True,
                'video_id': video_id,
                'segments': result,
                'language': language,
                'is_generated': is_generated,
            }), 200
        else:
            logger.info(f"Successfully fetched transcript ({len(result)} chars)")
            return jsonify({
                'success': True,
                'video_id': video_id,
                'transcript': result,
                'language': language,
                'is_generated': is_generated,
                'word_count': len(result.split()),
            }), 200

    except TranscriptsDisabled:
        logger.warning(f"Transcripts disabled for video: {video_id}")
        return jsonify({
            'success': False,
            'error': 'Transcripts are disabled for this video',
            'video_id': video_id
        }), 403

    except NoTranscriptFound:
        logger.warning(f"No transcript found for video: {video_id}")
        return jsonify({
            'success': False,
            'error': 'No transcript found for this video',
            'video_id': video_id
        }), 404

    except VideoUnavailable:
        logger.warning(f"Video unavailable: {video_id}")
        return jsonify({
            'success': False,
            'error': 'Video is unavailable or does not exist',
            'video_id': video_id
        }), 404

    except RequestBlocked:
        logger.error(f"Request blocked by YouTube for video: {video_id}")
        return jsonify({
            'success': False,
            'error': 'Request blocked by YouTube',
            'video_id': video_id
        }), 429

    except Exception as e:
        logger.error(f"Unexpected error for {video_id}: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'An error occurred while fetching the transcript',
            'hint': str(e),
            'video_id': video_id
        }), 500


@app.route('/transcript', methods=['POST'])
@require_api_key
def get_transcript_from_url():
    """Get transcript from a full YouTube URL."""
    data = request.get_json()

    if not data or 'url' not in data:
        return jsonify({
            'success': False,
            'error': 'Missing "url" in request body'
        }), 400

    video_id = extract_video_id(data['url'])

    if not video_id:
        return jsonify({
            'success': False,
            'error': 'Invalid YouTube URL or video ID'
        }), 400

    return get_transcript_endpoint(video_id)


@app.route('/debug/<video_id>', methods=['GET'])
@require_api_key
def debug_transcripts(video_id):
    """List all available transcripts for a video."""
    if not is_valid_video_id(video_id):
        return jsonify({'success': False, 'error': 'Invalid video ID'}), 400

    try:
        transcript_list = ytt_api.list(video_id)
        available = []
        for t in transcript_list:
            available.append({
                'language': t.language,
                'language_code': t.language_code,
                'is_generated': t.is_generated,
                'is_translatable': t.is_translatable
            })
        return jsonify({
            'success': True,
            'video_id': video_id,
            'available_transcripts': available,
            'count': len(available)
        }), 200
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'video_id': video_id
        }), 500


# =============================================================================
# ROUTES - AI
# =============================================================================

@app.route('/ai/complete', methods=['POST'])
@require_api_key
def ai_complete():
    """Generate AI completion."""
    data = request.get_json()

    if not data or 'prompt' not in data:
        return jsonify({
            'success': False,
            'error': 'Missing "prompt" in request body'
        }), 400

    prompt = data['prompt']
    max_tokens = data.get('max_tokens', 2048)
    temperature = data.get('temperature', 0.7)

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


# =============================================================================
# ERROR HANDLERS
# =============================================================================

@app.errorhandler(404)
def not_found(error):
    return jsonify({
        'success': False,
        'error': 'Endpoint not found'
    }), 404


@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Internal server error: {str(error)}")
    return jsonify({
        'success': False,
        'error': 'Internal server error'
    }), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
