from flask import Flask, jsonify, request
from flask_cors import CORS
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable,
    TooManyRequests,
    YouTubeRequestFailed
)
import os
import re
import logging

app = Flask(__name__)
CORS(app)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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

@app.route('/')
def home():
    """Health check endpoint"""
    return jsonify({
        'status': 'ok',
        'service': 'YouTube Transcript API',
        'version': '1.0.0',
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
def get_transcript(video_id):
    """Get transcript for a YouTube video"""
    try:
        logger.info(f"Fetching transcript for video: {video_id}")
        
        # Get preferred language from query params
        preferred_lang = request.args.get('lang', 'en')
        
        # Fetch transcript with retry logic
        try:
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        except Exception as e:
            logger.error(f"Error listing transcripts: {str(e)}")
            raise
        
        # Try to get transcript in preferred language
        transcript = None
        try:
            transcript = transcript_list.find_transcript([preferred_lang])
            logger.info(f"Found transcript in {preferred_lang}")
        except NoTranscriptFound:
            logger.info(f"No transcript in {preferred_lang}, trying alternatives")
            # Try manually created transcripts first
            if transcript_list._manually_created_transcripts:
                transcript = list(transcript_list._manually_created_transcripts.values())[0]
                logger.info(f"Using manually created transcript in {transcript.language_code}")
            # Fall back to auto-generated
            elif transcript_list._generated_transcripts:
                transcript = list(transcript_list._generated_transcripts.values())[0]
                logger.info(f"Using auto-generated transcript in {transcript.language_code}")
            else:
                raise NoTranscriptFound("No transcripts available")
        
        # Fetch the actual transcript data
        try:
            transcript_data = transcript.fetch()
        except Exception as e:
            logger.error(f"Error fetching transcript data: {str(e)}")
            raise
        
        # Combine all text segments
        full_text = ' '.join([entry['text'] for entry in transcript_data])
        
        # Clean up the text
        full_text = full_text.replace('\n', ' ').replace('  ', ' ').strip()
        
        logger.info(f"Successfully fetched transcript ({len(full_text)} chars)")
        
        # Return transcript with metadata
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
        logger.warning(f"Transcripts disabled for video: {video_id}")
        return jsonify({
            'success': False,
            'error': 'Transcripts are disabled for this video',
            'video_id': video_id
        }), 400
        
    except NoTranscriptFound:
        logger.warning(f"No transcript found for video: {video_id}")
        return jsonify({
            'success': False,
            'error': 'No transcript found for this video. The video may not have captions available.',
            'video_id': video_id
        }), 404
        
    except VideoUnavailable:
        logger.warning(f"Video unavailable: {video_id}")
        return jsonify({
            'success': False,
            'error': 'Video is unavailable or does not exist',
            'video_id': video_id
        }), 404
        
    except TooManyRequests:
        logger.error(f"Rate limited for video: {video_id}")
        return jsonify({
            'success': False,
            'error': 'Too many requests. Please try again later.',
            'video_id': video_id
        }), 429
        
    except YouTubeRequestFailed as e:
        logger.error(f"YouTube request failed for {video_id}: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Failed to fetch from YouTube: {str(e)}',
            'video_id': video_id
        }), 503
        
    except Exception as e:
        logger.error(f"Unexpected error for {video_id}: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'An error occurred: {str(e)}',
            'video_id': video_id,
            'hint': 'This video may not have transcripts available or may be region-restricted'
        }), 500

@app.route('/transcript', methods=['POST'])
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
    logger.error(f"Internal server error: {str(error)}")
    return jsonify({
        'success': False,
        'error': 'Internal server error'
    }), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)


# File: requirements.txt
"""
Flask==3.0.0
flask-cors==4.0.0
youtube-transcript-api==0.6.2
gunicorn==21.2.0
"""

# File: Procfile (for Railway/Heroku)
"""
web: gunicorn app:app
"""
