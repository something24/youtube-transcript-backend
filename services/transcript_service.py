"""
YouTube transcript fetching service.
"""

import re
import logging
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import NoTranscriptFound

logger = logging.getLogger(__name__)

# Initialize the transcript API client
ytt_api = YouTubeTranscriptApi()


def get_transcript(video_id: str, include_timestamps: bool = False):
    """
    Fetch transcript using youtube-transcript-api.

    Args:
        video_id: YouTube video ID
        include_timestamps: If True, return segments with timing info

    Returns:
        tuple: (transcript_text_or_segments, language_code, is_generated)
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

    # Fall back to any available transcript and try to translate to English
    if transcript is None:
        try:
            for t in transcript_list:
                transcript = t
                is_generated = t.is_generated
                language = t.language_code
                logger.info(f"Found transcript in {language}")

                # Try to translate to English if not already English
                if not language.startswith('en') and t.is_translatable:
                    try:
                        transcript = transcript.translate('en')
                        language = 'en'
                        logger.info("Translated to English")
                    except Exception as te:
                        logger.warning(f"Translation failed, using original: {te}")
                break
        except Exception as e:
            logger.error(f"Error getting fallback transcript: {e}")
            raise Exception(f"No transcript found for video {video_id}")

    if transcript is None:
        raise Exception(f"No transcript available for video {video_id}")

    # Fetch transcript data
    transcript_data = transcript.fetch()

    if include_timestamps:
        # Return segments with timing information
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
        # Combine into plain text
        transcript_text = ' '.join([entry.text for entry in transcript_data])
        transcript_text = re.sub(r'\s+', ' ', transcript_text).strip()
        transcript_text = re.sub(r'\[.*?\]', '', transcript_text)
        return transcript_text, language, is_generated


def list_available_transcripts(video_id: str) -> list:
    """List all available transcripts for a video."""
    transcript_list = ytt_api.list(video_id)
    available = []

    for t in transcript_list:
        available.append({
            'language': t.language,
            'language_code': t.language_code,
            'is_generated': t.is_generated,
            'is_translatable': t.is_translatable
        })

    return available
