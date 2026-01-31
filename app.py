"""
YTSummary Backend API

Flask application for:
- YouTube transcript fetching
- AI completion proxy (Gemini)
"""

# Setup path FIRST before any other imports
import sys
import os
_app_dir = os.path.dirname(os.path.abspath(__file__))
if _app_dir not in sys.path:
    sys.path.insert(0, _app_dir)

import logging
from flask import Flask, jsonify
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from routes.transcript import transcript_bp
from routes.ai import ai_bp

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

# Register blueprints
app.register_blueprint(transcript_bp)
app.register_blueprint(ai_bp)


# Health check endpoints
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


# Error handlers
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
