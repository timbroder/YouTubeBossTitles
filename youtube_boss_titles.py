#!/usr/bin/env python3
"""
YouTube Boss Title Updater
Automatically updates PS5 game videos with boss names
"""

import argparse
import base64
import logging
import os
import re
import subprocess
import tempfile
import time
from collections import defaultdict
from datetime import datetime
from typing import Optional

import gspread
import openai
import yt_dlp
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn, TimeRemainingColumn
from rich.table import Table

from boss_scraper import BossScraper
from config import Config
from database import VideoDatabase, exponential_backoff
from error_messages import ErrorCode, format_error
from gaming_api import GamingAPI
from logging_config import log_api_call, log_error, setup_logging

__version__ = "1.1.0"

# Initialize rich console
console = Console()

# Logger will be initialized in main() with user preferences
logger = None


# API scopes
SCOPES = [
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]

# Souls-like games that should get "Melee" in the title
SOULSLIKE_GAMES = [
    "bloodborne",
    "dark souls",
    "demon's souls",
    "demons souls",
    "sekiro",
    "lords of the fallen",
    "lies of p",
    "nioh",
    "mortal shell",
    "salt and sanctuary",
    "hollow knight",
    "the surge",
    "remnant",
]


class YouTubeBossUpdater:
    def __init__(
        self, config: Config, logger_instance: Optional[logging.Logger] = None, db_path: str = "processed_videos.db"
    ) -> None:
        """
        Initialize the updater with configuration.

        Args:
            config: Configuration object with all settings
            logger_instance: Optional logger instance (creates default if not provided)
            db_path: Path to SQLite database file (or ':memory:' for in-memory)

        Example:
            >>> config = Config()
            >>> updater = YouTubeBossUpdater(config)
            >>> updater.authenticate_youtube()
        """
        self.config = config
        self.youtube = None
        self.sheets_client = None
        self.log_sheet = None
        self.error_sheet = None  # Separate sheet for errors
        self.log_spreadsheet_name = config.get("youtube.log_spreadsheet_name")
        self.openai_client = openai.OpenAI(api_key=config.get("openai.api_key"))
        self.processed_videos = set()  # Track processed video IDs from sheets
        self.db = VideoDatabase(db_path)
        self.max_retries = config.get("processing.retry.max_attempts", 3)
        self.logger = logger_instance or logging.getLogger("youtube_boss_updater")
        self.gaming_api = GamingAPI(
            cache_expiry_days=config.get("processing.cache.expiry_days", 30), logger=self.logger
        )
        self.boss_scraper = BossScraper(logger=self.logger)

    def authenticate_youtube(self) -> None:
        """
        Authenticate with YouTube API using OAuth 2.0.

        Creates YouTube API and Google Sheets clients. Handles token refresh
        and initial authentication flow if needed.

        Raises:
            FileNotFoundError: If client_secret.json is not found
            Exception: If authentication fails

        Example:
            >>> updater = YouTubeBossUpdater(config)
            >>> updater.authenticate_youtube()
            ✓ YouTube authentication successful
        """
        creds = None

        # Token file stores user's access and refresh tokens
        if os.path.exists("token.json"):
            creds = Credentials.from_authorized_user_file("token.json", SCOPES)

        # If no valid credentials, let user log in
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not os.path.exists("client_secret.json"):
                    raise FileNotFoundError(
                        "client_secret.json not found. Please download it from Google Cloud Console."
                    )
                flow = InstalledAppFlow.from_client_secrets_file("client_secret.json", SCOPES)
                creds = flow.run_local_server(port=0)

            # Save credentials for next run
            with open("token.json", "w") as token:
                token.write(creds.to_json())

        self.youtube = build("youtube", "v3", credentials=creds)
        print("✓ YouTube authentication successful")
        self.logger.info("YouTube API authentication successful")

        # Initialize Google Sheets client
        self.sheets_client = gspread.authorize(creds)
        print("✓ Google Sheets authentication successful")
        self.logger.info("Google Sheets authentication successful")

    def setup_log_spreadsheet(self) -> None:
        """
        Create or open the log spreadsheet and set up headers.

        Creates a Google Sheet with two tabs: "Processed Videos" and "Errors".
        Loads previously processed video IDs from the sheet to avoid duplicates.

        Example:
            >>> updater.setup_log_spreadsheet()
            ✓ Opened existing log spreadsheet: YouTube Boss Title Updates
        """
        try:
            # Try to open existing spreadsheet
            spreadsheet = self.sheets_client.open(self.log_spreadsheet_name)
            self.log_sheet = spreadsheet.sheet1
            print(f"✓ Opened existing log spreadsheet: {self.log_spreadsheet_name}")

            # Try to get or create the Errors sheet
            try:
                self.error_sheet = spreadsheet.worksheet("Errors")
            except gspread.exceptions.WorksheetNotFound:
                self.error_sheet = spreadsheet.add_worksheet(title="Errors", rows="1000", cols="10")
                self._setup_error_sheet_headers()

            # Load already processed video IDs from sheets
            self._load_processed_videos()
        except gspread.exceptions.SpreadsheetNotFound:
            # Create new spreadsheet
            spreadsheet = self.sheets_client.create(self.log_spreadsheet_name)
            self.log_sheet = spreadsheet.sheet1
            self.log_sheet.update_title("Processed Videos")

            # Set up headers for main sheet
            headers = ["Timestamp", "Original Title", "New Title", "Playlist Name", "Video Link", "Playlist Link"]
            self.log_sheet.append_row(headers)

            # Format header row (bold)
            self.log_sheet.format("A1:F1", {"textFormat": {"bold": True}})

            # Create and setup errors sheet
            self.error_sheet = spreadsheet.add_worksheet(title="Errors", rows="1000", cols="10")
            self._setup_error_sheet_headers()

            print(f"✓ Created new log spreadsheet: {self.log_spreadsheet_name}")
            print(f"  Spreadsheet URL: {spreadsheet.url}")

    def _setup_error_sheet_headers(self) -> None:
        """Setup headers for the Errors sheet."""
        if not self.error_sheet:
            return

        error_headers = [
            "Timestamp",
            "Video ID",
            "Video Title",
            "Game Name",
            "Error Type",
            "Error Message",
            "Attempts",
            "Video Link",
        ]
        self.error_sheet.append_row(error_headers)
        self.error_sheet.format("A1:H1", {"textFormat": {"bold": True}})

    def _load_processed_videos(self) -> None:
        """Load video IDs that have already been processed from Google Sheets."""
        if not self.log_sheet:
            return

        try:
            # Get all video links from the sheet (column E)
            records = self.log_sheet.get_all_records()
            for record in records:
                video_link = record.get("Video Link", "")
                if video_link and "watch?v=" in video_link:
                    video_id = video_link.split("watch?v=")[1].split("&")[0]
                    self.processed_videos.add(video_id)

            print(f"  Loaded {len(self.processed_videos)} already processed videos from sheets")
        except Exception as e:
            print(f"  ⚠ Warning: Could not load processed videos: {e}")

    def log_video_update(
        self, video_id: str, original_title: str, new_title: str, playlist_name: str, playlist_id: Optional[str]
    ) -> None:
        """
        Log video update to Google Sheets.

        Args:
            video_id: YouTube video ID
            original_title: Original PS5 title
            new_title: Updated title with boss name
            playlist_name: Name of the playlist
            playlist_id: YouTube playlist ID (or None if not added to playlist)

        Example:
            >>> updater.log_video_update(
            ...     "abc123", "Bloodborne_20250101120000",
            ...     "Bloodborne: Father Gascoigne Melee PS5",
            ...     "Bloodborne", "PLabc123"
            ... )
        """
        if not self.log_sheet:
            print("  ⚠ Warning: Log sheet not initialized, skipping logging")
            return

        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            video_link = f"https://www.youtube.com/watch?v={video_id}"
            playlist_link = f"https://www.youtube.com/playlist?list={playlist_id}" if playlist_id else "N/A"

            row = [timestamp, original_title, new_title, playlist_name, video_link, playlist_link]

            self.log_sheet.append_row(row)
            print("  ✓ Logged update to spreadsheet")

        except Exception as e:
            print(f"  ⚠ Warning: Failed to log to spreadsheet: {e}")

    def log_error_to_sheet(
        self, video_id: str, video_title: str, game_name: str, error_type: str, error_message: str, attempts: int = 1
    ) -> None:
        """
        Log error to Google Sheets Errors tab.

        Args:
            video_id: YouTube video ID
            video_title: Title of the video
            game_name: Extracted game name
            error_type: Type of error (e.g., 'boss_identification_failed')
            error_message: Detailed error message
            attempts: Number of attempts made
        """
        if not self.error_sheet:
            self.logger.warning("Error sheet not initialized, skipping error logging")
            return

        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            video_link = f"https://www.youtube.com/watch?v={video_id}"

            # Truncate error message if too long
            max_error_length = 500
            if len(error_message) > max_error_length:
                error_message = error_message[:max_error_length] + "..."

            row = [timestamp, video_id, video_title, game_name, error_type, error_message, attempts, video_link]

            self.error_sheet.append_row(row)
            self.logger.debug(f"Logged error to spreadsheet for video {video_id}")

        except Exception as e:
            self.logger.warning(f"Failed to log error to spreadsheet: {e}")

    def is_default_ps5_title(self, title: str) -> bool:
        """
        Check if video title matches PS5 default pattern.

        Args:
            title: Video title to check

        Returns:
            True if title matches PS5 pattern (GameName_YYYYMMDDHHMMSS)

        Example:
            >>> updater.is_default_ps5_title("Bloodborne_20250101120000")
            True
            >>> updater.is_default_ps5_title("My Custom Title")
            False
        """
        # Pattern: GameName_YYYYMMDDHHMMSS or GameName_YYYYMMDDHHMMSS
        pattern = r".+_\d{14}$"
        return bool(re.match(pattern, title))

    def extract_game_name(self, title: str) -> str:
        """
        Extract game name from PS5 default title.

        Args:
            title: PS5 title with timestamp

        Returns:
            Game name without timestamp

        Example:
            >>> updater.extract_game_name("Bloodborne_20250101120000")
            'Bloodborne'
        """
        # Remove timestamp pattern
        game_name = re.sub(r"_\d{14}$", "", title)
        return game_name.strip()

    def is_soulslike(self, game_name: str) -> bool:
        """
        Check if game is a souls-like that should get 'Melee' tag.

        Uses RAWG API for dynamic detection with fallback to hardcoded list.

        Args:
            game_name: Name of the game to check

        Returns:
            True if game is souls-like

        Example:
            >>> updater.is_soulslike("Bloodborne")
            True
            >>> updater.is_soulslike("Clair Obscur")
            False
        """
        return self.gaming_api.is_soulslike_game(game_name)

    def get_my_videos(self) -> list[dict[str, str]]:
        """
        Fetch all videos from user's channel.

        Returns:
            List of video dictionaries with 'id', 'title', and 'published_at' keys

        Example:
            >>> videos = updater.get_my_videos()
            >>> len(videos)
            150
            >>> videos[0].keys()
            dict_keys(['id', 'title', 'published_at'])
        """
        videos = []

        # Get the uploads playlist ID
        channels_response = self.youtube.channels().list(part="contentDetails", mine=True).execute()

        if not channels_response.get("items"):
            print("No channel found")
            return videos

        uploads_playlist_id = channels_response["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

        # Get all videos from uploads playlist
        next_page_token = None

        while True:
            playlist_response = (
                self.youtube.playlistItems()
                .list(part="snippet", playlistId=uploads_playlist_id, maxResults=50, pageToken=next_page_token)
                .execute()
            )

            for item in playlist_response.get("items", []):
                video_id = item["snippet"]["resourceId"]["videoId"]
                title = item["snippet"]["title"]

                videos.append({"id": video_id, "title": title, "published_at": item["snippet"]["publishedAt"]})

            next_page_token = playlist_response.get("nextPageToken")
            if not next_page_token:
                break

        return videos

    def get_video_thumbnail_url(self, video_id: str) -> str:
        """
        Get the default YouTube thumbnail URL.

        Args:
            video_id: YouTube video ID

        Returns:
            URL to the video's max resolution thumbnail

        Example:
            >>> updater.get_video_thumbnail_url("abc123")
            'https://img.youtube.com/vi/abc123/maxresdefault.jpg'
        """
        return f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"

    def extract_video_frames(self, video_id: str, timestamps: Optional[list[int]] = None) -> list[str]:
        """
        Extract frames from video at specific timestamps using yt-dlp.

        Downloads first 90 seconds of video and extracts frames at specified
        timestamps using ffmpeg.

        Args:
            video_id: YouTube video ID
            timestamps: List of timestamps in seconds (defaults to config values)

        Returns:
            List of base64-encoded image data URLs

        Example:
            >>> frames = updater.extract_video_frames("abc123", [10, 20, 30])
            >>> len(frames)
            3
            >>> frames[0].startswith("data:image/jpeg;base64,")
            True
        """
        if timestamps is None:
            # Get timestamps from config
            timestamps = self.config.get("processing.frame_extraction.timestamps", [10, 20, 30, 45, 60])

        print(f"  Extracting frames from video at timestamps: {timestamps}")

        frames = []
        temp_dir = tempfile.mkdtemp()

        try:
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            video_path = os.path.join(temp_dir, "video.mp4")

            # Download first 90 seconds of video
            quality = self.config.get("processing.frame_extraction.quality", "worst")
            ydl_opts = {
                "format": f"{quality}[ext=mp4]",  # Use configured quality
                "outtmpl": video_path,
                "quiet": True,
                "no_warnings": True,
                "download_ranges": lambda info, ydl: [{"start_time": 0, "end_time": 90}],
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([video_url])

            if not os.path.exists(video_path):
                print("  ✗ Failed to download video")
                return frames

            # Extract frames at specified timestamps using ffmpeg
            for i, timestamp in enumerate(timestamps):
                frame_path = os.path.join(temp_dir, f"frame_{i}.jpg")

                try:
                    # Use ffmpeg to extract frame at timestamp
                    subprocess.run(
                        [
                            "ffmpeg",
                            "-ss",
                            str(timestamp),
                            "-i",
                            video_path,
                            "-frames:v",
                            "1",
                            "-q:v",
                            "2",
                            "-y",
                            frame_path,
                        ],
                        check=True,
                        capture_output=True,
                        timeout=10,
                    )

                    if os.path.exists(frame_path):
                        # Convert to base64 for OpenAI API
                        with open(frame_path, "rb") as f:
                            image_data = base64.b64encode(f.read()).decode("utf-8")
                            frames.append(f"data:image/jpeg;base64,{image_data}")

                except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                    print(f"  ⚠ Failed to extract frame at {timestamp}s")
                    continue

            print(f"  ✓ Extracted {len(frames)} frames")

        except Exception as e:
            print(f"  ✗ Error extracting frames: {e}")

        finally:
            # Cleanup temp files
            try:
                import shutil

                shutil.rmtree(temp_dir)
            except Exception:
                pass

        return frames

    def get_boss_list(self, game_name: str) -> list[str]:
        """
        Get comprehensive boss list for the game from wikis.

        Args:
            game_name: Name of the game

        Returns:
            List of known boss names from Wikipedia and Fandom wikis

        Example:
            >>> updater = YouTubeBossUpdater(config)
            >>> bosses = updater.get_boss_list("Bloodborne")
            >>> len(bosses) > 0
            True
        """
        try:
            boss_list = self.boss_scraper.get_boss_list(game_name, use_cache=True)
            self.logger.info(f"Retrieved {len(boss_list)} bosses for {game_name}")
            return boss_list
        except Exception as e:
            self.logger.error(f"Failed to get boss list for {game_name}: {e}")
            return []

    def identify_boss_from_images(self, image_urls: list[str], game_name: str) -> Optional[str]:
        """
        Use OpenAI Vision to identify boss from one or more images.

        Args:
            image_urls: List of image URLs or base64-encoded data URLs
            game_name: Name of the game

        Returns:
            Boss name if identified, None otherwise

        Example:
            >>> images = ["data:image/jpeg;base64,/9j/4AAQ..."]
            >>> boss = updater.identify_boss_from_images(images, "Bloodborne")
            >>> boss
            'Father Gascoigne'
        """
        # Get potential boss list
        boss_list = self.get_boss_list(game_name)
        boss_context = f"\n\nKnown bosses in {game_name}: {', '.join(boss_list)}" if boss_list else ""

        # Build content with text prompt and all images
        content = [
            {
                "type": "text",
                "text": f"""These are screenshots from a {game_name} gameplay video.

Please identify the boss being fought in these images. Look for:
1. Boss health bars or names displayed on screen
2. Large enemy characters that appear to be bosses
3. Arena or environment indicators
4. Boss introduction text or cutscenes

If you can identify a specific boss name, respond with ONLY the boss name.
If you cannot identify a specific boss, respond with "Unknown Boss".{boss_context}

Boss name:""",
            }
        ]

        # Add all image URLs
        for url in image_urls:
            content.append({"type": "image_url", "image_url": {"url": url}})

        try:
            model = self.config.get("openai.model", "gpt-4o")
            max_tokens = self.config.get("openai.max_tokens", 100)

            response = self.openai_client.chat.completions.create(
                model=model, messages=[{"role": "user", "content": content}], max_tokens=max_tokens
            )

            boss_name = response.choices[0].message.content.strip()

            if boss_name and boss_name != "Unknown Boss":
                return boss_name
            else:
                return None

        except Exception as e:
            print(f"  ✗ Error calling OpenAI API: {e}")
            return None

    def identify_boss(self, video_id: str, game_name: str, attempt: int = 0) -> Optional[str]:
        """
        Use OpenAI Vision to identify the boss in the video
        Hybrid approach: Try cache first, then thumbnail, then extract video frames if needed
        Includes retry logic with exponential backoff
        """
        print(f"  Analyzing video {video_id} for boss identification...")
        self.logger.info(
            f"Starting boss identification for video {video_id}", extra={"video_id": video_id, "game_name": game_name}
        )

        # Check cache first if enabled
        cache_enabled = self.config.get("processing.cache.enabled", True)
        if cache_enabled:
            cached_result = self.db.get_cached_boss(video_id, game_name)
            if cached_result:
                boss_name = cached_result["boss_name"]
                print(f"  ✓ Found in cache: {boss_name} (source: {cached_result['source']})")
                self.logger.info(
                    f"Boss found in cache: {boss_name}",
                    extra={"video_id": video_id, "game_name": game_name, "cache_hit": True},
                )
                return boss_name

        try:
            # Step 1: Try with thumbnail first (fast and free)
            print("  Trying thumbnail first...")
            log_api_call(self.logger, "youtube_thumbnail", video_id)
            thumbnail_url = self.get_video_thumbnail_url(video_id)
            boss_name = self.identify_boss_from_images([thumbnail_url], game_name)

            if boss_name:
                print(f"  ✓ Identified boss from thumbnail: {boss_name}")
                self.logger.info(
                    f"Boss identified from thumbnail: {boss_name}", extra={"video_id": video_id, "game_name": game_name}
                )

                # Cache the result
                if cache_enabled:
                    expiry_days = self.config.get("processing.cache.expiry_days", 30)
                    self.db.cache_boss(video_id, game_name, boss_name, source="thumbnail", expiry_days=expiry_days)

                return boss_name

            # Step 2: Thumbnail didn't work, extract actual video frames
            print("  Thumbnail didn't work, extracting frames from video...")
            self.logger.debug("Thumbnail identification failed, extracting video frames", extra={"video_id": video_id})
            frames = self.extract_video_frames(video_id)

            if not frames:
                print("  ✗ Could not extract frames from video")
                log_error(
                    self.logger,
                    "frame_extraction_failed",
                    "Could not extract frames from video",
                    video_id=video_id,
                    game_name=game_name,
                )
                return None

            # Try to identify boss from extracted frames
            log_api_call(self.logger, "openai_vision_frames", video_id, frame_count=len(frames))
            boss_name = self.identify_boss_from_images(frames, game_name)

            if boss_name:
                print(f"  ✓ Identified boss from video frames: {boss_name}")
                self.logger.info(
                    f"Boss identified from frames: {boss_name}", extra={"video_id": video_id, "game_name": game_name}
                )

                # Cache the result
                if cache_enabled:
                    expiry_days = self.config.get("processing.cache.expiry_days", 30)
                    self.db.cache_boss(video_id, game_name, boss_name, source="frames", expiry_days=expiry_days)

                return boss_name
            else:
                print("  ✗ Could not identify boss even from video frames")
                log_error(
                    self.logger,
                    "boss_identification_failed",
                    "Could not identify boss from video frames",
                    video_id=video_id,
                    game_name=game_name,
                )
                return None

        except Exception as e:
            # If this is a retryable error and we haven't exceeded max retries
            if attempt < self.max_retries - 1:
                delay = exponential_backoff(attempt)
                print(f"  ⚠ Error: {e}")
                print(f"  Retrying in {delay:.1f} seconds (attempt {attempt + 1}/{self.max_retries})...")
                self.logger.warning(
                    f"Retry {attempt + 1}/{self.max_retries} after error: {e}", extra={"video_id": video_id}
                )
                time.sleep(delay)
                return self.identify_boss(video_id, game_name, attempt + 1)
            else:
                print(f"  ✗ Failed after {self.max_retries} attempts: {e}")
                log_error(
                    self.logger,
                    "max_retries_exceeded",
                    f"Failed after {self.max_retries} attempts: {e}",
                    video_id=video_id,
                    game_name=game_name,
                    exc_info=True,
                )
                raise

    def format_title(self, game_name: str, boss_name: str) -> str:
        """
        Format the video title according to specifications.

        Args:
            game_name: Name of the game
            boss_name: Name of the boss

        Returns:
            Formatted title with or without 'Melee' tag

        Example:
            >>> updater.format_title("Bloodborne", "Father Gascoigne")
            'Bloodborne: Father Gascoigne Melee PS5'
            >>> updater.format_title("Clair Obscur", "Final Boss")
            'Clair Obscur: Final Boss PS5'
        """
        is_souls = self.is_soulslike(game_name)

        if is_souls:
            return f"{game_name}: {boss_name} Melee PS5"
        else:
            return f"{game_name}: {boss_name} PS5"

    def update_video_title(self, video_id: str, new_title: str) -> bool:
        """
        Update the video title on YouTube.

        Args:
            video_id: YouTube video ID
            new_title: New title to set

        Returns:
            True if update successful, False otherwise

        Example:
            >>> success = updater.update_video_title(
            ...     "abc123",
            ...     "Bloodborne: Father Gascoigne Melee PS5"
            ... )
            >>> success
            True
        """
        try:
            # Get current video details
            video_response = self.youtube.videos().list(part="snippet", id=video_id).execute()

            if not video_response.get("items"):
                print(f"  ✗ Video {video_id} not found")
                return False

            video = video_response["items"][0]
            snippet = video["snippet"]

            # Update title
            snippet["title"] = new_title

            # Update video
            self.youtube.videos().update(part="snippet", body={"id": video_id, "snippet": snippet}).execute()

            print(f"  ✓ Title updated to: {new_title}")
            return True

        except Exception as e:
            print(f"  ✗ Error updating title: {e}")
            return False

    def get_or_create_playlist(self, game_name: str) -> Optional[str]:
        """
        Get existing playlist for game or create new one.

        Args:
            game_name: Name of the game

        Returns:
            Playlist ID if successful, None otherwise

        Example:
            >>> playlist_id = updater.get_or_create_playlist("Bloodborne")
            >>> playlist_id
            'PLabc123xyz'
        """
        # Search for existing playlist
        playlists_response = self.youtube.playlists().list(part="snippet", mine=True, maxResults=50).execute()

        for playlist in playlists_response.get("items", []):
            if playlist["snippet"]["title"].lower() == game_name.lower():
                print(f"  ✓ Found existing playlist: {game_name}")
                return playlist["id"]

        # Create new playlist
        try:
            playlist_response = (
                self.youtube.playlists()
                .insert(
                    part="snippet,status",
                    body={
                        "snippet": {"title": game_name, "description": f"PS5 gameplay videos for {game_name}"},
                        "status": {"privacyStatus": "public"},
                    },
                )
                .execute()
            )

            playlist_id = playlist_response["id"]
            print(f"  ✓ Created new playlist: {game_name}")
            return playlist_id

        except Exception as e:
            print(f"  ✗ Error creating playlist: {e}")
            return None

    def add_video_to_playlist(self, video_id: str, playlist_id: str) -> bool:
        """
        Add video to playlist.

        Args:
            video_id: YouTube video ID
            playlist_id: YouTube playlist ID

        Returns:
            True if successful, False otherwise

        Example:
            >>> success = updater.add_video_to_playlist("abc123", "PLabc123")
            >>> success
            True
        """
        try:
            self.youtube.playlistItems().insert(
                part="snippet",
                body={
                    "snippet": {"playlistId": playlist_id, "resourceId": {"kind": "youtube#video", "videoId": video_id}}
                },
            ).execute()

            print("  ✓ Added to playlist")
            return True

        except Exception as e:
            # Check if video is already in playlist
            if "videoAlreadyInPlaylist" in str(e):
                print("  ℹ Video already in playlist")
                return True
            print(f"  ✗ Error adding to playlist: {e}")
            return False

    def process_video(self, video: dict[str, str], force: bool = False) -> bool:
        """
        Process a single video with database tracking and error handling.

        Args:
            video: Video dictionary with 'id' and 'title' keys
            force: If True, reprocess already-processed videos

        Returns:
            True if successfully processed, False otherwise

        Example:
            >>> video = {'id': 'abc123', 'title': 'Bloodborne_20250101120000'}
            >>> success = updater.process_video(video)
            >>> success
            True
        """
        video_id = video["id"]
        title = video["title"]

        print(f"\nProcessing: {title} ({video_id})")

        # Check database for existing record
        db_record = self.db.get_video(video_id)

        # Check if already processed (unless force flag is set)
        if not force:
            if video_id in self.processed_videos:
                print("  ⊘ Already processed (in sheets), skipping (use --force to reprocess)")
                return False

            if db_record and db_record["status"] == "completed":
                print("  ⊘ Already processed (in database), skipping (use --force to reprocess)")
                return False

        # Check if it's a default PS5 title
        if not self.is_default_ps5_title(title):
            print("  ⊘ Not a default PS5 title, skipping")
            return False

        # Extract game name
        game_name = self.extract_game_name(title)
        print(f"  Game: {game_name}")

        # Add to database if not already there
        if not db_record:
            self.db.add_video(video_id, title, game_name, status="pending")

        # Mark as processing
        self.db.update_video_status(video_id, "processing")

        try:
            # Identify boss
            boss_name = self.identify_boss(video_id, game_name)
            if not boss_name:
                print("  ⊘ Could not identify boss")
                error_msg = "Could not identify boss from video"
                self.db.update_video_status(video_id, "failed", error_message=error_msg)
                self.log_error_to_sheet(
                    video_id=video_id,
                    video_title=title,
                    game_name=game_name,
                    error_type="boss_identification_failed",
                    error_message=error_msg,
                    attempts=1,
                )
                return False

            # Format new title
            new_title = self.format_title(game_name, boss_name)

            # Store original title for logging
            original_title = title

            # Update title
            if not self.update_video_title(video_id, new_title):
                error_msg = "Failed to update video title"
                self.db.update_video_status(video_id, "failed", error_message=error_msg)
                self.log_error_to_sheet(
                    video_id=video_id,
                    video_title=title,
                    game_name=game_name,
                    error_type="title_update_failed",
                    error_message=error_msg,
                    attempts=1,
                )
                return False

            # Get or create playlist
            playlist_id = self.get_or_create_playlist(game_name)
            if playlist_id:
                self.add_video_to_playlist(video_id, playlist_id)

            # Log the update to Google Sheets
            self.log_video_update(
                video_id=video_id,
                original_title=original_title,
                new_title=new_title,
                playlist_name=game_name,
                playlist_id=playlist_id,
            )

            # Mark as completed in database
            self.db.update_video_status(video_id, "completed", new_title=new_title, boss_name=boss_name)

            # Add to processed set
            self.processed_videos.add(video_id)

            return True

        except Exception as e:
            print(f"  ✗ Error processing video: {e}")
            log_error(
                self.logger,
                error_type="processing_error",
                message=f"Error processing video: {e}",
                video_id=video_id,
                game_name=game_name,
                exc_info=True,
            )

            # Get attempts from database
            db_record = self.db.get_video(video_id)
            attempts = db_record["attempts"] if db_record else 1

            self.db.update_video_status(video_id, "failed", error_message=str(e))

            # Log error to Google Sheets
            self.log_error_to_sheet(
                video_id=video_id,
                video_title=title,
                game_name=game_name,
                error_type="processing_error",
                error_message=str(e),
                attempts=attempts,
            )
            return False

    def list_games(self) -> None:
        """
        List all detected games with video counts.

        Fetches all videos and displays a summary of detected games
        with their video counts.

        Example:
            >>> updater.list_games()
            Found 150 videos with default PS5 titles
            Detected games:
            --------------------------------------------------
              Bloodborne: 25 video(s) [SOULS-LIKE]
              Clair Obscur: 10 video(s)
        """
        print("Fetching videos...")
        videos = self.get_my_videos()

        # Group by game name
        game_counts = defaultdict(int)
        ps5_videos = 0

        for video in videos:
            if self.is_default_ps5_title(video["title"]):
                ps5_videos += 1
                game_name = self.extract_game_name(video["title"])
                game_counts[game_name] += 1

        print(f"\nFound {ps5_videos} videos with default PS5 titles")
        print("\nDetected games:")
        print("-" * 50)

        # Sort by count descending
        for game_name, count in sorted(game_counts.items(), key=lambda x: x[1], reverse=True):
            souls_tag = " [SOULS-LIKE]" if self.is_soulslike(game_name) else ""
            print(f"  {game_name}: {count} video(s){souls_tag}")

    def run(
        self,
        dry_run: bool = False,
        video_id: Optional[str] = None,
        game: Optional[str] = None,
        limit: Optional[int] = None,
        force: bool = False,
        resume: bool = False,
        workers: Optional[int] = None,
    ) -> None:
        """
        Main execution function.

        Args:
            dry_run: If True, preview changes without making them
            video_id: Process only this specific video ID
            game: Filter videos by game name
            limit: Process only N videos (after filtering)
            force: Reprocess already-processed videos
            resume: Resume processing pending and failed videos
            workers: Number of parallel workers (None for sequential)

        Example:
            >>> updater.run(dry_run=True, game="Bloodborne", limit=5)
            [DRY RUN MODE - No changes will be made]
        """
        # Print header
        console.print()
        console.print(
            Panel(
                f"[bold cyan]YouTube Boss Title Updater[/bold cyan]\n[dim]Version {__version__}[/dim]",
                border_style="cyan",
                box=box.DOUBLE,
            )
        )

        # Clear any stuck 'processing' status from previous runs
        if not dry_run:
            self.db.clear_processing_status()

        # Show database statistics
        if not dry_run:
            stats = self.db.get_statistics()
            cache_stats = self.db.get_cache_statistics()

            if stats.get("total", 0) > 0 or cache_stats.get("total", 0) > 0:
                console.print("\n[bold]Database Status:[/bold]")
                table = Table(show_header=False, box=None, padding=(0, 2))
                table.add_column("Label", style="cyan")
                table.add_column("Value", justify="right")

                if stats.get("total", 0) > 0:
                    table.add_row("Total tracked", str(stats.get("total", 0)))
                    table.add_row("Completed", f"[green]{stats.get('completed', 0)}[/green]")
                    table.add_row("Failed", f"[red]{stats.get('failed', 0)}[/red]")
                    table.add_row("Pending", f"[yellow]{stats.get('pending', 0)}[/yellow]")

                if cache_stats.get("total", 0) > 0:
                    table.add_row("", "")  # Spacer
                    table.add_row(
                        "Cache entries",
                        f"[cyan]{cache_stats.get('active', 0)}[/cyan] active, [dim]{cache_stats.get('expired', 0)} expired[/dim]",
                    )

                console.print(table)

            # Cleanup expired cache entries
            if cache_stats.get("expired", 0) > 0:
                expired_cleaned = self.db.cleanup_expired_cache()
                if expired_cleaned > 0:
                    console.print(f"[dim]  Cleaned up {expired_cleaned} expired cache entries[/dim]")

        # Authenticate
        self.authenticate_youtube()

        # Setup log spreadsheet
        if not dry_run:
            print("\nSetting up log spreadsheet...")
            self.setup_log_spreadsheet()

        # Handle resume mode
        if resume and not dry_run:
            console.print("\n[bold yellow]🔄 RESUME MODE[/bold yellow] - Processing pending and failed videos...\n")
            pending = self.db.get_pending_videos()
            failed = self.db.get_failed_videos(max_attempts=self.max_retries)

            videos_to_process = []
            for record in pending + failed:
                videos_to_process.append(
                    {"id": record["video_id"], "title": record["original_title"], "published_at": ""}
                )

            if videos_to_process:
                console.print(f"[cyan]Found {len(videos_to_process)} videos to resume[/cyan]\n")
                self._process_video_list(videos_to_process, dry_run, force, workers)
            else:
                console.print("[yellow]No videos to resume[/yellow]")
            return

        # Get all videos
        console.print("\n[bold]Fetching videos...[/bold]")
        videos = self.get_my_videos()
        console.print(f"[cyan]Found {len(videos)} total videos[/cyan]")

        # Filter for specific video ID if provided
        if video_id:
            videos = [v for v in videos if v["id"] == video_id]
            if not videos:
                console.print(f"\n[red]Error: Video ID {video_id} not found![/red]")
                return
            console.print(f"[cyan]Processing specific video: {video_id}[/cyan]")

        # Filter for default PS5 titles
        ps5_videos = [v for v in videos if self.is_default_ps5_title(v["title"])]
        console.print(f"[cyan]Found {len(ps5_videos)} videos with default PS5 titles[/cyan]")

        # Filter by game name if provided
        if game:
            ps5_videos = [v for v in ps5_videos if game.lower() in self.extract_game_name(v["title"]).lower()]
            console.print(f"[cyan]Filtered to {len(ps5_videos)} videos matching game '{game}'[/cyan]")

        # Apply limit if provided
        if limit and limit > 0:
            ps5_videos = ps5_videos[:limit]
            console.print(f"[cyan]Limited to {len(ps5_videos)} videos[/cyan]")

        if not ps5_videos:
            console.print("\n[yellow]No videos to process![/yellow]")
            return

        self._process_video_list(ps5_videos, dry_run, force, workers)

    def _estimate_cost(self, num_videos: int) -> dict[str, float]:
        """
        Estimate processing costs.

        Args:
            num_videos: Number of videos to process

        Returns:
            Dictionary with cost breakdown

        Note:
            Rough estimates:
            - Thumbnail analysis: $0.002 per video (1 image, gpt-4o)
            - Frame extraction: $0.010 per video (5 images, gpt-4o) if thumbnail fails
            - Assume 50% need frame extraction
        """
        thumbnail_cost = num_videos * 0.002
        frame_cost = num_videos * 0.5 * 0.010
        total_cost = thumbnail_cost + frame_cost

        return {
            "thumbnail": thumbnail_cost,
            "frame_extraction": frame_cost,
            "total": total_cost,
            "per_video": total_cost / num_videos if num_videos > 0 else 0,
        }

    def _show_cost_estimate(self, num_videos: int) -> None:
        """
        Display cost estimate in a nice table.

        Args:
            num_videos: Number of videos to process
        """
        costs = self._estimate_cost(num_videos)

        table = Table(title="💰 Estimated Processing Cost", box=box.ROUNDED)
        table.add_column("Item", style="cyan", no_wrap=True)
        table.add_column("Cost", justify="right", style="green")

        table.add_row("Videos to process", str(num_videos))
        table.add_row("Thumbnail analysis", f"${costs['thumbnail']:.4f}")
        table.add_row("Frame extraction (50%)", f"${costs['frame_extraction']:.4f}")
        table.add_row("Total estimated", f"${costs['total']:.4f}", style="bold green")
        table.add_row("Per video", f"${costs['per_video']:.4f}", style="dim")

        console.print()
        console.print(table)
        console.print()

    def _process_video_list(
        self, videos: list[dict[str, str]], dry_run: bool, force: bool, workers: Optional[int] = None
    ) -> None:
        """
        Process a list of videos with rich progress bar and optional parallel processing.

        Args:
            videos: List of video dictionaries
            dry_run: If True, preview without making changes
            force: Reprocess already-processed videos
            workers: Number of parallel workers (None for sequential)
        """
        if dry_run:
            console.print("\n[yellow][DRY RUN MODE - No changes will be made][/yellow]\n")

        # Show cost estimate
        if not dry_run:
            self._show_cost_estimate(len(videos))

        # Determine if we should use parallel processing
        use_parallel = False
        if workers is not None and workers > 1:
            use_parallel = True
        elif workers is None:
            # Check config
            parallel_enabled = self.config.get("processing.parallel.enabled", False)
            if parallel_enabled:
                workers = self.config.get("processing.parallel.workers", 3)
                use_parallel = True

        if use_parallel and not dry_run:
            console.print(f"\n[bold cyan]Using parallel processing with {workers} workers[/bold cyan]\n")
            self._process_video_list_parallel(videos, force, workers)
            return

        # Sequential processing
        processed = 0
        failed = 0
        skipped = 0
        rate_limit = self.config.get("youtube.rate_limit_delay", 2)

        # Create progress bar
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeRemainingColumn(),
            console=console,
        ) as progress:

            task = progress.add_task("[cyan]Processing videos...", total=len(videos))

            for i, video in enumerate(videos, 1):
                video_title = video["title"][:50] + "..." if len(video["title"]) > 50 else video["title"]
                progress.update(task, description=f"[cyan]Processing: {video_title}")

                if dry_run:
                    console.print(
                        f"\n[dim][{i}/{len(videos)}][/dim] [yellow][DRY RUN][/yellow] Would process: {video['title']}"
                    )
                    game_name = self.extract_game_name(video["title"])
                    console.print(f"  Game: {game_name}")
                    console.print(f"  Souls-like: {self.is_soulslike(game_name)}")
                else:
                    result = self.process_video(video, force=force)
                    if result:
                        processed += 1
                        console.print("[green]✓[/green] Processed successfully", style="dim")
                    elif result is False:
                        # Check if it was skipped or failed
                        video_id = video["id"]
                        db_record = self.db.get_video(video_id)
                        if db_record and db_record["status"] == "failed":
                            failed += 1
                            console.print("[red]✗[/red] Failed", style="dim")
                        else:
                            skipped += 1
                            console.print("[yellow]⊘[/yellow] Skipped", style="dim")

                    # Rate limiting
                    if i < len(videos):  # Don't sleep after last video
                        time.sleep(rate_limit)

                progress.update(task, advance=1)

        # Print summary
        self._print_summary(len(videos), processed, failed, skipped, dry_run)

    def _print_summary(self, total: int, processed: int, failed: int, skipped: int, dry_run: bool) -> None:
        """
        Print processing summary with rich formatting.

        Args:
            total: Total number of videos
            processed: Number of successfully processed videos
            failed: Number of failed videos
            skipped: Number of skipped videos
            dry_run: Whether this was a dry run
        """
        console.print()

        if dry_run:
            console.print(
                Panel(f"[yellow]Would process {total} videos[/yellow]", title="Dry Run Summary", border_style="yellow")
            )
        else:
            # Create summary table
            table = Table(title="📊 Processing Summary", box=box.ROUNDED)
            table.add_column("Status", style="cyan", no_wrap=True)
            table.add_column("Count", justify="right")
            table.add_column("Percentage", justify="right")

            def pct(count):
                return f"{(count / total * 100):.1f}%" if total > 0 else "0%"

            table.add_row("[green]Processed[/green]", str(processed), f"[green]{pct(processed)}[/green]")
            table.add_row("[red]Failed[/red]", str(failed), f"[red]{pct(failed)}[/red]")
            table.add_row("[yellow]Skipped[/yellow]", str(skipped), f"[yellow]{pct(skipped)}[/yellow]")
            table.add_row("[cyan]Total[/cyan]", str(total), "100%", style="bold")

            console.print()
            console.print(table)

            # Show database statistics
            stats = self.db.get_statistics()

            console.print()
            table2 = Table(title="💾 Database Totals", box=box.ROUNDED)
            table2.add_column("Status", style="cyan")
            table2.add_column("Count", justify="right")

            table2.add_row("[green]Completed[/green]", str(stats.get("completed", 0)))
            table2.add_row("[red]Failed[/red]", str(stats.get("failed", 0)))
            table2.add_row("[yellow]Pending[/yellow]", str(stats.get("pending", 0)))
            table2.add_row("[cyan]Total[/cyan]", str(stats.get("total", 0)), style="bold")

            console.print(table2)
            console.print()

    def _process_video_list_parallel(self, videos: list[dict[str, str]], force: bool, workers: int) -> None:
        """
        Process videos in parallel using ThreadPoolExecutor.

        Args:
            videos: List of video dictionaries
            force: Reprocess already-processed videos
            workers: Number of parallel workers
        """
        import threading
        from concurrent.futures import ThreadPoolExecutor, as_completed

        # Create thread-safe lock for shared resources
        lock = threading.Lock()
        results = {"processed": 0, "failed": 0, "skipped": 0}

        def process_video_wrapper(video: dict) -> dict:
            """Wrapper to process video and return result"""
            try:
                result = self.process_video(video, force=force)

                with lock:
                    if result:
                        results["processed"] += 1
                        return {"status": "processed", "video": video}
                    else:
                        # Check if it was skipped or failed
                        video_id = video["id"]
                        db_record = self.db.get_video(video_id)
                        if db_record and db_record["status"] == "failed":
                            results["failed"] += 1
                            return {"status": "failed", "video": video}
                        else:
                            results["skipped"] += 1
                            return {"status": "skipped", "video": video}
            except Exception as e:
                with lock:
                    results["failed"] += 1
                return {"status": "error", "video": video, "error": str(e)}

        # Create progress bar
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeRemainingColumn(),
            console=console,
        ) as progress:

            task = progress.add_task(f"[cyan]Processing videos with {workers} workers...", total=len(videos))

            # Process videos in parallel
            with ThreadPoolExecutor(max_workers=workers) as executor:
                # Submit all videos to the executor
                future_to_video = {executor.submit(process_video_wrapper, video): video for video in videos}

                # Process completed futures as they finish
                for future in as_completed(future_to_video):
                    video = future_to_video[future]
                    try:
                        result = future.result()
                        status = result["status"]

                        if status == "processed":
                            console.print(f"[green]✓[/green] {video['title'][:50]}... processed", style="dim")
                        elif status == "failed" or status == "error":
                            console.print(f"[red]✗[/red] {video['title'][:50]}... failed", style="dim")
                        else:
                            console.print(f"[yellow]⊘[/yellow] {video['title'][:50]}... skipped", style="dim")

                    except Exception as e:
                        console.print(f"[red]✗[/red] {video['title'][:50]}... error: {e}", style="dim")
                        with lock:
                            results["failed"] += 1

                    progress.update(task, advance=1)

        # Print summary
        self._print_summary(len(videos), results["processed"], results["failed"], results["skipped"], False)


def main() -> int:
    """
    Main entry point.

    Returns:
        Exit code (0 for success, non-zero for errors)

    Example:
        >>> exit_code = main()
        >>> exit_code
        0
    """
    parser = argparse.ArgumentParser(
        description="YouTube Boss Title Updater - Automatically update PS5 game videos with boss names",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --dry-run                      # Preview changes without applying
  %(prog)s --video-id abc123 --force      # Process specific video
  %(prog)s --game "Bloodborne" --limit 5  # Process 5 Bloodborne videos
  %(prog)s --list-games                   # Show all detected games
  %(prog)s --config prod.yml              # Use custom config file
        """,
    )

    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    parser.add_argument("--dry-run", action="store_true", help="Preview what would be done without making changes")

    parser.add_argument(
        "--config", type=str, metavar="PATH", help="Path to custom configuration file (default: use built-in config)"
    )

    parser.add_argument("--video-id", type=str, metavar="ID", help="Process only this specific video ID")

    parser.add_argument(
        "--game", type=str, metavar="NAME", help="Filter videos by game name (case-insensitive partial match)"
    )

    parser.add_argument("--limit", type=int, metavar="N", help="Process only N videos (after filtering)")

    parser.add_argument("--force", action="store_true", help="Reprocess videos that have already been processed")

    parser.add_argument("--list-games", action="store_true", help="List all detected games with video counts and exit")

    parser.add_argument(
        "--resume", action="store_true", help="Resume processing pending and failed videos from database"
    )

    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose output (DEBUG level logging)")

    parser.add_argument("--quiet", "-q", action="store_true", help="Minimal output (WARNING level and above only)")

    parser.add_argument(
        "--clear-cache", action="store_true", help="Clear all cached boss identification results and exit"
    )

    parser.add_argument(
        "--workers",
        type=int,
        metavar="N",
        help="Number of parallel workers for video processing (default: 1 for sequential, recommend 3-5 for parallel)",
    )

    parser.add_argument(
        "--rollback",
        type=str,
        metavar="VIDEO_ID",
        help="Rollback a specific video to its original title",
    )

    parser.add_argument(
        "--rollback-all",
        action="store_true",
        help="Rollback all updated videos to their original titles",
    )

    parser.add_argument(
        "--list-rollback-candidates",
        action="store_true",
        help="List all videos that can be rolled back and exit",
    )

    args = parser.parse_args()

    # Setup logging
    global logger
    logger = setup_logging(
        log_level="INFO", verbose=args.verbose, quiet=args.quiet, console_output=True, json_format=True
    )

    logger.info(f"YouTube Boss Title Updater v{__version__} starting")

    # Load configuration
    try:
        config = Config(config_path=args.config)
        config.validate()
        logger.info("Configuration loaded and validated")
    except FileNotFoundError as e:
        error_msg = format_error(ErrorCode.CONFIG_NOT_FOUND, str(e))
        console.print(f"\n[red]{error_msg}[/red]\n")
        logger.error(f"Configuration file not found: {e}")
        return 1
    except ValueError as e:
        error_msg = format_error(ErrorCode.CONFIG_INVALID, str(e))
        console.print(f"\n[red]{error_msg}[/red]\n")
        logger.error(f"Configuration validation error: {e}")
        return 1

    # Create updater
    updater = YouTubeBossUpdater(config, logger_instance=logger)

    # Authenticate first
    try:
        updater.authenticate_youtube()
    except FileNotFoundError as e:
        error_msg = format_error(ErrorCode.CLIENT_SECRET_NOT_FOUND, str(e))
        console.print(f"\n[red]{error_msg}[/red]\n")
        logger.error(f"Client secret not found: {e}", exc_info=True)
        return 1
    except Exception as e:
        error_msg = format_error(ErrorCode.AUTH_FAILED, str(e))
        console.print(f"\n[red]{error_msg}[/red]\n")
        logger.error(f"Authentication failed: {e}", exc_info=True)
        return 1

    # Handle --clear-cache
    if args.clear_cache:
        console.print("\n[bold yellow]Clearing cache...[/bold yellow]")
        total_cleared, expired_cleared = updater.db.clear_cache()
        console.print(f"[green]✓[/green] Cleared {total_cleared} cache entries ({expired_cleared} were expired)")
        logger.info(f"Cache cleared: {total_cleared} total, {expired_cleared} expired")
        return 0

    # Handle rollback commands
    if args.rollback or args.rollback_all or args.list_rollback_candidates:
        from rollback import RollbackManager

        rollback_manager = RollbackManager(updater, logger)

        if args.list_rollback_candidates:
            rollback_manager.display_rollback_candidates()
            return 0

        if args.rollback:
            success = rollback_manager.rollback_video(args.rollback, confirm=True, update_sheets=True)
            return 0 if success else 1

        if args.rollback_all:
            success_count, failed_count = rollback_manager.rollback_all(confirm=True, update_sheets=True)
            return 0 if failed_count == 0 else 1

    # Handle --list-games
    if args.list_games:
        updater.list_games()
        return 0

    # Run the updater with specified options
    try:
        updater.run(
            dry_run=args.dry_run,
            video_id=args.video_id,
            game=args.game,
            limit=args.limit,
            force=args.force,
            resume=args.resume,
            workers=args.workers,
        )
        logger.info("Processing completed successfully")
    except KeyboardInterrupt:
        print("\n\nProcess interrupted by user")
        logger.warning("Process interrupted by user")
        return 130
    except Exception as e:
        print(f"\nError during execution: {e}")
        logger.critical(f"Fatal error during execution: {e}", exc_info=True)
        import traceback

        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
