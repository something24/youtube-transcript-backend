from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable,
    NoTranscriptAvailable,
    RequestBlocked
)
import os
import re
import logging

# Initialize the transcript API client
ytt_api = YouTubeTranscriptApi()

app = Flask(__name__)
CORS(app)

# Rate limiting - configurable via environment
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["100 per hour", "10 per minute"]
)

# Limit max request body size (1KB should be plenty for a URL)
app.config['MAX_CONTENT_LENGTH'] = 1024

# API key for authentication (set in Railway environment variables)
APP_API_KEY = os.environ.get('APP_API_KEY')

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def require_api_key(f):
    """Decorator to require API key for protected endpoints"""
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not APP_API_KEY:
            # If no API key configured, allow requests (for backwards compatibility during setup)
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

def extract_video_id(url):
    """Extract video ID from various YouTube URL formats"""
    patterns = [
        r'(?:youtube\.com/watch\?v=)([a-zA-Z0-9_-]{11})',
        r'(?:youtu\.be/)([a-zA-Z0-9_-]{11})',
        r'(?:youtube\.com/embed/)([a-zA-Z0-9_-]{11})',
        r'(?:youtube\.com/v/)([a-zA-Z0-9_-]{11})',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    
    if re.match(r'^[a-zA-Z0-9_-]{11}$', url):
        return url
    
    return None

def get_transcript(video_id):
    """
    Fetch transcript using youtube-transcript-api v1.x
    Returns: tuple (transcript_text, language_code, is_generated)
    """
    logger.info(f"Fetching transcript for video: {video_id}")

    # Try to get transcript - prefer manual captions, fall back to auto-generated
    transcript_list = ytt_api.list(video_id)

    transcript = None
    is_generated = False
    language = 'en'

    # First try to get manually created English transcript
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

    # Fall back to any available transcript and translate to English
    if transcript is None:
        try:
            # Get any available transcript
            for t in transcript_list:
                transcript = t
                is_generated = t.is_generated
                language = t.language_code
                logger.info(f"Found transcript in {language}, will translate to English")
                # Translate to English if not already English
                if not language.startswith('en'):
                    transcript = transcript.translate('en')
                    language = 'en'
                break
        except Exception as e:
            logger.error(f"Error getting fallback transcript: {e}")
            raise NoTranscriptAvailable(video_id)

    if transcript is None:
        raise NoTranscriptAvailable(video_id)

    # Fetch and combine transcript text
    transcript_data = transcript.fetch()
    transcript_text = ' '.join([entry.text for entry in transcript_data])

    # Clean up the text
    transcript_text = re.sub(r'\s+', ' ', transcript_text).strip()
    transcript_text = re.sub(r'\[.*?\]', '', transcript_text)  # Remove [Music], [Applause], etc.

    return transcript_text, language, is_generated

@app.route('/')
def home():
    """Health check endpoint"""
    return jsonify({
        'status': 'ok',
        'service': 'YouTube Transcript API',
        'version': '3.0.0',
        'method': 'youtube-transcript-api',
        'endpoints': {
            '/health': 'Health check',
            '/transcript/<video_id>': 'Get transcript by video ID',
            '/transcript (POST)': 'Get transcript by URL'
        }
    })

@app.route('/health')
def health():
    """Health check for monitoring"""
    return jsonify({'status': 'healthy'}), 200

@app.route('/transcript/<video_id>', methods=['GET'])
@require_api_key
def get_transcript_endpoint(video_id):
    """Get transcript for a YouTube video"""
    # Validate video_id format
    if not re.match(r'^[a-zA-Z0-9_-]{11}$', video_id):
        return jsonify({
            'success': False,
            'error': 'Invalid video ID format'
        }), 400

    try:
        # Get transcript using youtube-transcript-api
        transcript, language, is_generated = get_transcript(video_id)

        if not transcript:
            raise NoTranscriptAvailable(video_id)

        logger.info(f"Successfully fetched transcript ({len(transcript)} chars)")

        # Return transcript with metadata
        return jsonify({
            'success': True,
            'video_id': video_id,
            'transcript': transcript,
            'language': language,
            'is_generated': is_generated,
            'word_count': len(transcript.split()),
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
            'hint': 'The video may not have captions available in any language',
            'video_id': video_id
        }), 404

    except NoTranscriptAvailable:
        logger.warning(f"No transcript available for video: {video_id}")
        return jsonify({
            'success': False,
            'error': 'No transcript available for this video',
            'hint': 'The video may not have captions available',
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
            'hint': 'YouTube may be rate-limiting requests. Please try again later.',
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
    """Get transcript from a full YouTube URL"""
    data = request.get_json()

    if not data or 'url' not in data:
        return jsonify({
            'success': False,
            'error': 'Missing "url" in request body'
        }), 400

    url = data['url']
    video_id = extract_video_id(url)

    if not video_id:
        return jsonify({
            'success': False,
            'error': 'Invalid YouTube URL or video ID'
        }), 400

    # Forward to the GET endpoint
    return get_transcript_endpoint(video_id)

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
