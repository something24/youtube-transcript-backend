"""
Input validation utilities.
"""

import re


def extract_video_id(url: str) -> str | None:
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

    # Check if it's already a video ID
    if re.match(r'^[a-zA-Z0-9_-]{11}$', url):
        return url

    return None


def is_valid_video_id(video_id: str) -> bool:
    """Check if a string is a valid YouTube video ID."""
    return bool(re.match(r'^[a-zA-Z0-9_-]{11}$', video_id))
