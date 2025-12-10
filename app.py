from flask import Flask, jsonify, request
from flask_cors import CORS
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable
)
import os
import re

app = Flask(__name__)
CORS(app)  # Enable CORS for iOS app

# Optional: API Key authentication
API_KEY = os.environ.get('API_KEY', 'your-secret-key')

def verify_api_key():
    """Verify API key from request headers"""
    provided_key = request.headers.get('X-API-Key')
    if not provided_key or provided_key != API_KEY:
        return False
    return True

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
    
    # If no pattern matches, assume it's already a video ID
    if re.match(r'^[a-zA-Z0-9_-]{11}$', url):
        return url
    
    return None

@app.route('/')
def home():
    """Health check endpoint"""
    return jsonify({
        'status': 'ok',
        'service': 'YouTube Transcript API',
        'version': '1.0.0'
    })

@app.route('/health')
def health():
    """Health check for monitoring"""
    return jsonify({'status': 'healthy'}), 200

@app.route('/transcript/<video_id>', methods=['GET'])
def get_transcript(video_id):
    """
    Get transcript for a YouTube video
    
    Args:
        video_id: YouTube video ID (11 characters)
    
    Query params:
        lang: Preferred language code (default: en)
        
    Returns:
        JSON with transcript text and metadata
    """
    # Optional: Verify API key
    # if not verify_api_key():
    #     return jsonify({'error': 'Invalid or missing API key'}), 401
    
    try:
        # Get preferred language from query params
        preferred_lang = request.args.get('lang', 'en')
        
        # Fetch transcript
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        
        # Try to get transcript in preferred language
        try:
            transcript = transcript_list.find_transcript([preferred_lang])
        except NoTranscriptFound:
            # Fallback to any available transcript
            transcript = transcript_list.find_transcript(
                transcript_list._manually_created_transcripts.keys() or
                transcript_list._generated_transcripts.keys()
            )
        
        # Get the actual transcript data
        transcript_data = transcript.fetch()
        
        # Combine all text segments
        full_text = ' '.join([entry['text'] for entry in transcript_data])
        
        # Clean up the text
        full_text = full_text.replace('\n', ' ').strip()
        
        # Get video metadata (language, etc)
        return jsonify({
            'success': True,
            'video_id': video_id,
            'transcript': full_text,
            'language': transcript.language_code,
            'is_generated': transcript.is_generated,
            'is_translatable': transcript.is_translatable,
            'word_count': len(full_text.split()),
        }), 200
        
    except TranscriptsDisabled:
        return jsonify({
            'success': False,
            'error': 'Transcripts are disabled for this video'
        }), 400
        
    except NoTranscriptFound:
        return jsonify({
            'success': False,
            'error': 'No transcript found for this video'
        }), 404
        
    except VideoUnavailable:
        return jsonify({
            'success': False,
            'error': 'Video is unavailable or does not exist'
        }), 404
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'An error occurred: {str(e)}'
        }), 500

@app.route('/transcript', methods=['POST'])
def get_transcript_from_url():
    """
    Get transcript from a full YouTube URL
    
    Body:
        {
            "url": "https://youtube.com/watch?v=..."
        }
    
    Returns:
        JSON with transcript text and metadata
    """
    # Optional: Verify API key
    # if not verify_api_key():
    #     return jsonify({'error': 'Invalid or missing API key'}), 401
    
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
    
    # Forward to the GET endpoint logic
    request.view_args = {'video_id': video_id}
    return get_transcript(video_id)

@app.route('/languages/<video_id>', methods=['GET'])
def get_available_languages(video_id):
    """Get all available transcript languages for a video"""
    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        
        languages = []
        
        # Get manually created transcripts
        for transcript in transcript_list._manually_created_transcripts.values():
            languages.append({
                'language': transcript.language,
                'language_code': transcript.language_code,
                'is_generated': False,
                'is_translatable': transcript.is_translatable
            })
        
        # Get auto-generated transcripts
        for transcript in transcript_list._generated_transcripts.values():
            languages.append({
                'language': transcript.language,
                'language_code': transcript.language_code,
                'is_generated': True,
                'is_translatable': transcript.is_translatable
            })
        
        return jsonify({
            'success': True,
            'video_id': video_id,
            'languages': languages
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.errorhandler(404)
def not_found(error):
    return jsonify({
        'success': False,
        'error': 'Endpoint not found'
    }), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({
        'success': False,
        'error': 'Internal server error'
    }), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
