"""
Transcript API routes.
"""

import logging
from flask import Blueprint, jsonify, request
from youtube_transcript_api._errors import (
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable,
    RequestBlocked
)

from utils.auth import require_api_key
from utils.validators import is_valid_video_id, extract_video_id
from services.transcript_service import get_transcript, list_available_transcripts

logger = logging.getLogger(__name__)

transcript_bp = Blueprint('transcript', __name__)


@transcript_bp.route('/transcript/<video_id>', methods=['GET'])
@require_api_key
def get_transcript_endpoint(video_id):
    """Get transcript for a YouTube video."""
    # Validate video_id format
    if not is_valid_video_id(video_id):
        return jsonify({
            'success': False,
            'error': 'Invalid video ID format'
        }), 400

    # Check if timestamps are requested
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
            'hint': 'YouTube may be rate-limiting. Please try again later.',
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


@transcript_bp.route('/transcript', methods=['POST'])
@require_api_key
def get_transcript_from_url():
    """Get transcript from a full YouTube URL."""
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

    return get_transcript_endpoint(video_id)


@transcript_bp.route('/debug/<video_id>', methods=['GET'])
@require_api_key
def debug_transcripts(video_id):
    """List all available transcripts for a video (for debugging)."""
    if not is_valid_video_id(video_id):
        return jsonify({'success': False, 'error': 'Invalid video ID'}), 400

    try:
        available = list_available_transcripts(video_id)
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
