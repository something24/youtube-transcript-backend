# YouTube Transcript Backend

A Flask-based REST API that extracts transcripts/captions from YouTube videos using yt-dlp.

## Deployment

- **Production URL:** https://web-production-29de.up.railway.app
- **Hosting:** Railway (auto-deploys from git)
- **To deploy changes:** Commit and push to the repository. Railway will automatically build and deploy.

## Project Structure

```
├── app.py              # Main Flask application (all API logic)
├── requirements.txt    # Python dependencies
├── Procfile            # Gunicorn deployment config
└── .gitignore
```

## Tech Stack

- **Flask 3.0** - Web framework
- **yt-dlp** - YouTube caption extraction
- **Flask-CORS** - Cross-origin support
- **Flask-Limiter** - Rate limiting (100/hour, 10/minute)
- **Gunicorn** - Production WSGI server

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Health check with service info |
| `/health` | GET | Monitoring endpoint |
| `/transcript/<video_id>` | GET | Fetch transcript by 11-char video ID |
| `/transcript` | POST | Fetch transcript from full YouTube URL (body: `{"url": "..."}`) |

## Development

```bash
pip install -r requirements.txt
python app.py
```

Server runs on `http://localhost:5000` by default.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | 5000 | Server port |
| `YTDLP_TIMEOUT` | 30 | yt-dlp subprocess timeout in seconds |
| `APP_API_KEY` | None | API key for authentication (required for `/transcript` endpoints) |

## Authentication

The `/transcript` endpoints require an `X-API-Key` header. Set the `APP_API_KEY` environment variable in Railway to enable authentication.

```bash
# Example request
curl -H "X-API-Key: your-secret-key" https://web-production-29de.up.railway.app/transcript/dQw4w9WgXcQ
```

If `APP_API_KEY` is not set, endpoints remain open (for backwards compatibility during setup).

## Key Implementation Details

- Video IDs are validated as 11-character alphanumeric strings before processing
- Transcripts are fetched via yt-dlp subprocess, writing VTT files to a temp directory
- VTT parsing strips timestamps, formatting tags, and metadata to return clean text
- English subtitles prioritized (en, en-US, en-GB)
- POST body limited to 1KB
