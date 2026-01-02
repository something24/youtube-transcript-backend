from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import os
import re
import logging
import subprocess
import tempfile

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

# Configurable timeout for yt-dlp (default 30 seconds)
YTDLP_TIMEOUT = int(os.environ.get('YTDLP_TIMEOUT', 30))

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

def get_transcript_with_ytdlp(video_id):
    """
    Fetch transcript using yt-dlp
    Returns: tuple (transcript_text, language_code, metadata)
    """
    try:
        video_url = f"https://www.youtube.com/watch?v={video_id}"

        logger.info(f"Running yt-dlp for video: {video_id}")

        # Create temporary directory for subtitle files
        with tempfile.TemporaryDirectory() as tmpdir:
            output_template = os.path.join(tmpdir, 'subtitle')

            cmd = [
                'yt-dlp',
                '--skip-download',
                '--write-auto-subs',
                '--write-subs',
                '--sub-langs', 'en,en-US,en-GB',
                '--sub-format', 'vtt',
                '--output', output_template,
                video_url
            ]

            # Run yt-dlp with cwd parameter (thread-safe)
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=YTDLP_TIMEOUT,
                cwd=tmpdir
            )

            if result.returncode != 0:
                logger.error(f"yt-dlp error: {result.stderr}")
                raise Exception("Failed to fetch subtitles")

            # Look for subtitle files in temp directory
            subtitle_files = [f for f in os.listdir(tmpdir) if f.endswith('.vtt')]

            if not subtitle_files:
                raise Exception("No subtitle files generated")

            # Read the subtitle file
            subtitle_path = os.path.join(tmpdir, subtitle_files[0])
            with open(subtitle_path, 'r', encoding='utf-8') as f:
                vtt_content = f.read()

            # Parse VTT content
            transcript = parse_vtt(vtt_content)

            return transcript, 'en', {'is_generated': 'auto' in subtitle_files[0].lower()}

    except subprocess.TimeoutExpired:
        raise Exception("Request timeout - video may be too long or unavailable")
    except Exception as e:
        logger.error(f"Error in get_transcript_with_ytdlp: {str(e)}")
        raise

def parse_vtt(vtt_content):
    """Parse VTT subtitle format and extract text"""
    lines = vtt_content.split('\n')
    transcript_parts = []
    
    for line in lines:
        line = line.strip()
        # Skip WEBVTT header, timestamps, and empty lines
        if (line and
            not line.startswith('WEBVTT') and
            not line.startswith('Kind:') and
            not line.startswith('Language:') and
            '-->' not in line and
            not line.startswith('NOTE') and
            not line.isdigit()):
            # Remove VTT formatting tags
            line = re.sub(r'<[^>]+>', '', line)
            if line:
                transcript_parts.append(line)
    
    # Join and clean up
    transcript = ' '.join(transcript_parts)
    transcript = re.sub(r'\s+', ' ', transcript).strip()
    
    return transcript

@app.route('/')
def home():
    """Health check endpoint"""
    return jsonify({
        'status': 'ok',
        'service': 'YouTube Transcript API',
        'version': '2.0.0',
        'method': 'yt-dlp',
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
def get_transcript(video_id):
    """Get transcript for a YouTube video"""
    # Validate video_id format to prevent command injection
    if not re.match(r'^[a-zA-Z0-9_-]{11}$', video_id):
        return jsonify({
            'success': False,
            'error': 'Invalid video ID format'
        }), 400

    try:
        logger.info(f"Fetching transcript for video: {video_id}")
        
        # Get transcript using yt-dlp
        transcript, language, metadata = get_transcript_with_ytdlp(video_id)
        
        if not transcript:
            raise Exception("No transcript content retrieved")
        
        logger.info(f"Successfully fetched transcript ({len(transcript)} chars)")
        
        # Return transcript with metadata
        return jsonify({
            'success': True,
            'video_id': video_id,
            'transcript': transcript,
            'language': language,
            'is_generated': metadata.get('is_generated', True),
            'word_count': len(transcript.split()),
        }), 200
        
    except subprocess.TimeoutExpired:
        logger.error(f"Timeout for video: {video_id}")
        return jsonify({
            'success': False,
            'error': 'Request timeout - video may be too long or unavailable',
            'video_id': video_id
        }), 408
        
    except Exception as e:
        error_msg = str(e).lower()
        
        if 'no subtitle' in error_msg or 'no transcript' in error_msg:
            logger.warning(f"No transcript found for video: {video_id}")
            return jsonify({
                'success': False,
                'error': 'No transcript found for this video. The video may not have captions available.',
                'video_id': video_id
            }), 404
        elif 'unavailable' in error_msg or 'not exist' in error_msg:
            logger.warning(f"Video unavailable: {video_id}")
            return jsonify({
                'success': False,
                'error': 'Video is unavailable or does not exist',
                'video_id': video_id
            }), 404
        elif 'private' in error_msg:
            logger.warning(f"Video is private: {video_id}")
            return jsonify({
                'success': False,
                'error': 'Video is private',
                'video_id': video_id
            }), 403
        else:
            # Log full error for debugging but return generic message to client
            logger.error(f"Unexpected error for {video_id}: {str(e)}")
            return jsonify({
                'success': False,
                'error': 'An error occurred while fetching the transcript',
                'video_id': video_id,
                'hint': 'This video may not have transcripts available or may be region-restricted'
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
    request.view_args = {'video_id': video_id}
    return get_transcript(video_id)

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
