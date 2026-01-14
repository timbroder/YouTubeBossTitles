"""
Error messages with codes and helpful troubleshooting hints
"""

from typing import Dict, Optional


class ErrorCode:
    """Error codes for different failure types"""

    AUTH_FAILED = "E001"
    CONFIG_NOT_FOUND = "E002"
    CONFIG_INVALID = "E003"
    CLIENT_SECRET_NOT_FOUND = "E004"
    API_RATE_LIMIT = "E005"
    BOSS_IDENTIFICATION_FAILED = "E006"
    VIDEO_NOT_FOUND = "E007"
    TITLE_UPDATE_FAILED = "E008"
    PLAYLIST_CREATE_FAILED = "E009"
    FRAME_EXTRACTION_FAILED = "E010"
    OPENAI_API_ERROR = "E011"
    YOUTUBE_API_ERROR = "E012"
    SHEETS_API_ERROR = "E013"
    NETWORK_ERROR = "E014"
    PROCESSING_ERROR = "E015"


ERROR_MESSAGES: Dict[str, Dict[str, str]] = {
    ErrorCode.AUTH_FAILED: {
        "message": "Authentication failed",
        "hint": "Make sure client_secret.json exists and is valid. Try deleting token.json to re-authenticate.",
        "docs": "https://developers.google.com/youtube/v3/guides/auth/server-side-web-apps",
    },
    ErrorCode.CONFIG_NOT_FOUND: {
        "message": "Configuration file not found",
        "hint": "Create a config.yml file based on config.yml.example or use --config to specify a custom config file.",
        "docs": "See README.md for configuration instructions",
    },
    ErrorCode.CONFIG_INVALID: {
        "message": "Configuration validation failed",
        "hint": "Check your config.yml file for missing or invalid values. Required fields: youtube.channel_id, openai.api_key",
        "docs": "See config.yml.example for correct format",
    },
    ErrorCode.CLIENT_SECRET_NOT_FOUND: {
        "message": "client_secret.json not found",
        "hint": "Download your OAuth 2.0 credentials from Google Cloud Console and save as client_secret.json",
        "docs": "https://console.cloud.google.com/apis/credentials",
    },
    ErrorCode.API_RATE_LIMIT: {
        "message": "API rate limit exceeded",
        "hint": "Wait a few minutes before retrying. Consider increasing youtube.rate_limit_delay in config.yml",
        "docs": "https://developers.google.com/youtube/v3/getting-started#quota",
    },
    ErrorCode.BOSS_IDENTIFICATION_FAILED: {
        "message": "Could not identify boss from video",
        "hint": "The video may not contain a clear boss fight scene. Try using --force to reprocess with different frames.",
        "docs": "",
    },
    ErrorCode.VIDEO_NOT_FOUND: {
        "message": "Video not found",
        "hint": "The video may have been deleted or is private. Check the video URL and permissions.",
        "docs": "",
    },
    ErrorCode.TITLE_UPDATE_FAILED: {
        "message": "Failed to update video title",
        "hint": "Check that your YouTube OAuth credentials have permission to edit videos.",
        "docs": "https://developers.google.com/youtube/v3/docs/videos/update",
    },
    ErrorCode.PLAYLIST_CREATE_FAILED: {
        "message": "Failed to create playlist",
        "hint": "Check YouTube quota limits and OAuth permissions. You may have too many playlists.",
        "docs": "https://developers.google.com/youtube/v3/docs/playlists/insert",
    },
    ErrorCode.FRAME_EXTRACTION_FAILED: {
        "message": "Could not extract frames from video",
        "hint": "Ensure ffmpeg is installed and the video URL is accessible. Try: ffmpeg -version",
        "docs": "https://ffmpeg.org/download.html",
    },
    ErrorCode.OPENAI_API_ERROR: {
        "message": "OpenAI API error",
        "hint": "Check your OpenAI API key in config.yml and ensure you have sufficient credits. Visit: https://platform.openai.com/account/billing",
        "docs": "https://platform.openai.com/docs/guides/error-codes",
    },
    ErrorCode.YOUTUBE_API_ERROR: {
        "message": "YouTube API error",
        "hint": "Check your quota limits at https://console.cloud.google.com/apis/api/youtube.googleapis.com/quotas",
        "docs": "https://developers.google.com/youtube/v3/docs/errors",
    },
    ErrorCode.SHEETS_API_ERROR: {
        "message": "Google Sheets API error",
        "hint": "Ensure Google Sheets API is enabled in your Google Cloud project.",
        "docs": "https://console.cloud.google.com/apis/library/sheets.googleapis.com",
    },
    ErrorCode.NETWORK_ERROR: {
        "message": "Network connection error",
        "hint": "Check your internet connection and try again. If using a proxy, ensure it's configured correctly.",
        "docs": "",
    },
    ErrorCode.PROCESSING_ERROR: {
        "message": "Unexpected error during processing",
        "hint": "Check the logs in logs/error.log for more details. Use --verbose for detailed output.",
        "docs": "",
    },
}


def format_error(error_code: str, details: Optional[str] = None) -> str:
    """
    Format an error message with code, hint, and documentation link

    Args:
        error_code: Error code from ErrorCode class
        details: Optional additional details about the error

    Returns:
        Formatted error message string
    """
    if error_code not in ERROR_MESSAGES:
        return f"Unknown error code: {error_code}"

    error_info = ERROR_MESSAGES[error_code]
    message = f"[{error_code}] {error_info['message']}"

    if details:
        message += f"\nDetails: {details}"

    if error_info["hint"]:
        message += f"\n💡 Hint: {error_info['hint']}"

    if error_info["docs"]:
        message += f"\n📚 Docs: {error_info['docs']}"

    return message


def get_error_hint(error_code: str) -> str:
    """Get just the hint for an error code"""
    if error_code in ERROR_MESSAGES:
        return ERROR_MESSAGES[error_code]["hint"]
    return ""


def get_error_docs(error_code: str) -> str:
    """Get just the documentation link for an error code"""
    if error_code in ERROR_MESSAGES:
        return ERROR_MESSAGES[error_code]["docs"]
    return ""
