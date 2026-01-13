#!/usr/bin/env python3
"""
YouTube Boss Title Updater
Automatically updates PS5 game videos with boss names
"""

import os
import re
import json
import base64
import tempfile
import subprocess
import argparse
from typing import List, Dict, Optional, Tuple
from datetime import datetime
from pathlib import Path
import time
from collections import defaultdict

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import openai
import requests
from PIL import Image
import yt_dlp
import gspread

from config import Config
from database import VideoDatabase, exponential_backoff
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeRemainingColumn
from rich.table import Table
from rich.panel import Panel
from rich import box

__version__ = "1.0.0"

# Initialize rich console
console = Console()


# API scopes
SCOPES = [
    'https://www.googleapis.com/auth/youtube.force-ssl',
    'https://www.googleapis.com/auth/spreadsheets'
]

# Souls-like games that should get "Melee" in the title
SOULSLIKE_GAMES = [
    'bloodborne',
    'dark souls',
    'demon\'s souls',
    'demons souls',
    'elden ring',
    'sekiro',
    'lords of the fallen',
    'lies of p',
    'nioh',
    'mortal shell',
    'salt and sanctuary',
    'hollow knight',
    'the surge',
    'remnant',
]


class YouTubeBossUpdater:
    def __init__(self, config: Config, db_path: str = 'processed_videos.db'):
        """Initialize the updater with configuration"""
        self.config = config
        self.youtube = None
        self.sheets_client = None
        self.log_sheet = None
        self.log_spreadsheet_name = config.get('youtube.log_spreadsheet_name')
        self.openai_client = openai.OpenAI(api_key=config.get('openai.api_key'))
        self.processed_videos = set()  # Track processed video IDs from sheets
        self.db = VideoDatabase(db_path)
        self.max_retries = config.get('processing.retry.max_attempts', 3)

    def authenticate_youtube(self):
        """Authenticate with YouTube API"""
        creds = None

        # Token file stores user's access and refresh tokens
        if os.path.exists('token.json'):
            creds = Credentials.from_authorized_user_file('token.json', SCOPES)

        # If no valid credentials, let user log in
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not os.path.exists('client_secret.json'):
                    raise FileNotFoundError(
                        "client_secret.json not found. Please download it from Google Cloud Console."
                    )
                flow = InstalledAppFlow.from_client_secrets_file('client_secret.json', SCOPES)
                creds = flow.run_local_server(port=0)

            # Save credentials for next run
            with open('token.json', 'w') as token:
                token.write(creds.to_json())

        self.youtube = build('youtube', 'v3', credentials=creds)
        print("✓ YouTube authentication successful")

        # Initialize Google Sheets client
        self.sheets_client = gspread.authorize(creds)
        print("✓ Google Sheets authentication successful")

    def setup_log_spreadsheet(self):
        """Create or open the log spreadsheet and set up headers"""
        try:
            # Try to open existing spreadsheet
            spreadsheet = self.sheets_client.open(self.log_spreadsheet_name)
            self.log_sheet = spreadsheet.sheet1
            print(f"✓ Opened existing log spreadsheet: {self.log_spreadsheet_name}")

            # Load already processed video IDs from sheets
            self._load_processed_videos()
        except gspread.exceptions.SpreadsheetNotFound:
            # Create new spreadsheet
            spreadsheet = self.sheets_client.create(self.log_spreadsheet_name)
            self.log_sheet = spreadsheet.sheet1

            # Set up headers
            headers = [
                'Timestamp',
                'Original Title',
                'New Title',
                'Playlist Name',
                'Video Link',
                'Playlist Link'
            ]
            self.log_sheet.append_row(headers)

            # Format header row (bold)
            self.log_sheet.format('A1:F1', {'textFormat': {'bold': True}})

            print(f"✓ Created new log spreadsheet: {self.log_spreadsheet_name}")
            print(f"  Spreadsheet URL: {spreadsheet.url}")

    def _load_processed_videos(self):
        """Load video IDs that have already been processed from Google Sheets"""
        if not self.log_sheet:
            return

        try:
            # Get all video links from the sheet (column E)
            records = self.log_sheet.get_all_records()
            for record in records:
                video_link = record.get('Video Link', '')
                if video_link and 'watch?v=' in video_link:
                    video_id = video_link.split('watch?v=')[1].split('&')[0]
                    self.processed_videos.add(video_id)

            print(f"  Loaded {len(self.processed_videos)} already processed videos from sheets")
        except Exception as e:
            print(f"  ⚠ Warning: Could not load processed videos: {e}")

    def log_video_update(self, video_id: str, original_title: str, new_title: str,
                        playlist_name: str, playlist_id: Optional[str]):
        """Log video update to Google Sheets"""
        if not self.log_sheet:
            print("  ⚠ Warning: Log sheet not initialized, skipping logging")
            return

        try:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            video_link = f"https://www.youtube.com/watch?v={video_id}"
            playlist_link = f"https://www.youtube.com/playlist?list={playlist_id}" if playlist_id else "N/A"

            row = [
                timestamp,
                original_title,
                new_title,
                playlist_name,
                video_link,
                playlist_link
            ]

            self.log_sheet.append_row(row)
            print(f"  ✓ Logged update to spreadsheet")

        except Exception as e:
            print(f"  ⚠ Warning: Failed to log to spreadsheet: {e}")

    def is_default_ps5_title(self, title: str) -> bool:
        """Check if video title matches PS5 default pattern"""
        # Pattern: GameName_YYYYMMDDHHMMSS or GameName_YYYYMMDDHHMMSS
        pattern = r'.+_\d{14}$'
        return bool(re.match(pattern, title))

    def extract_game_name(self, title: str) -> str:
        """Extract game name from PS5 default title"""
        # Remove timestamp pattern
        game_name = re.sub(r'_\d{14}$', '', title)
        return game_name.strip()

    def is_soulslike(self, game_name: str) -> bool:
        """Check if game is a souls-like that should get 'Melee' tag"""
        game_lower = game_name.lower()
        soulslike_games = self.config.get('soulslike_games', SOULSLIKE_GAMES)
        return any(souls_game in game_lower for souls_game in soulslike_games)

    def get_my_videos(self) -> List[Dict]:
        """Fetch all videos from user's channel"""
        videos = []

        # Get the uploads playlist ID
        channels_response = self.youtube.channels().list(
            part='contentDetails',
            mine=True
        ).execute()

        if not channels_response.get('items'):
            print("No channel found")
            return videos

        uploads_playlist_id = channels_response['items'][0]['contentDetails']['relatedPlaylists']['uploads']

        # Get all videos from uploads playlist
        next_page_token = None

        while True:
            playlist_response = self.youtube.playlistItems().list(
                part='snippet',
                playlistId=uploads_playlist_id,
                maxResults=50,
                pageToken=next_page_token
            ).execute()

            for item in playlist_response.get('items', []):
                video_id = item['snippet']['resourceId']['videoId']
                title = item['snippet']['title']

                videos.append({
                    'id': video_id,
                    'title': title,
                    'published_at': item['snippet']['publishedAt']
                })

            next_page_token = playlist_response.get('nextPageToken')
            if not next_page_token:
                break

        return videos

    def get_video_thumbnail_url(self, video_id: str) -> str:
        """Get the default YouTube thumbnail URL"""
        return f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"

    def extract_video_frames(self, video_id: str, timestamps: List[int] = None) -> List[str]:
        """
        Extract frames from video at specific timestamps using yt-dlp
        Returns list of base64-encoded image data URLs
        """
        if timestamps is None:
            # Get timestamps from config
            timestamps = self.config.get('processing.frame_extraction.timestamps', [10, 20, 30, 45, 60])

        print(f"  Extracting frames from video at timestamps: {timestamps}")

        frames = []
        temp_dir = tempfile.mkdtemp()

        try:
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            video_path = os.path.join(temp_dir, 'video.mp4')

            # Download first 90 seconds of video
            quality = self.config.get('processing.frame_extraction.quality', 'worst')
            ydl_opts = {
                'format': f'{quality}[ext=mp4]',  # Use configured quality
                'outtmpl': video_path,
                'quiet': True,
                'no_warnings': True,
                'download_ranges': lambda info, ydl: [{'start_time': 0, 'end_time': 90}],
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([video_url])

            if not os.path.exists(video_path):
                print(f"  ✗ Failed to download video")
                return frames

            # Extract frames at specified timestamps using ffmpeg
            for i, timestamp in enumerate(timestamps):
                frame_path = os.path.join(temp_dir, f'frame_{i}.jpg')

                try:
                    # Use ffmpeg to extract frame at timestamp
                    subprocess.run([
                        'ffmpeg',
                        '-ss', str(timestamp),
                        '-i', video_path,
                        '-frames:v', '1',
                        '-q:v', '2',
                        '-y',
                        frame_path
                    ], check=True, capture_output=True, timeout=10)

                    if os.path.exists(frame_path):
                        # Convert to base64 for OpenAI API
                        with open(frame_path, 'rb') as f:
                            image_data = base64.b64encode(f.read()).decode('utf-8')
                            frames.append(f"data:image/jpeg;base64,{image_data}")

                except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
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

    def get_boss_list(self, game_name: str) -> List[str]:
        """
        Search for boss list for the game online
        This is a simplified version - could be enhanced with web scraping
        """
        # For now, return empty list - the LLM will identify the boss from the video
        # In a more sophisticated version, you could scrape wikis, use gaming APIs, etc.
        return []

    def identify_boss_from_images(self, image_urls: List[str], game_name: str) -> Optional[str]:
        """Use OpenAI Vision to identify boss from one or more images"""
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

Boss name:"""
            }
        ]

        # Add all image URLs
        for url in image_urls:
            content.append({
                "type": "image_url",
                "image_url": {"url": url}
            })

        try:
            model = self.config.get('openai.model', 'gpt-4o')
            max_tokens = self.config.get('openai.max_tokens', 100)

            response = self.openai_client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": content}],
                max_tokens=max_tokens
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
        Hybrid approach: Try thumbnail first, then extract video frames if needed
        Includes retry logic with exponential backoff
        """
        print(f"  Analyzing video {video_id} for boss identification...")

        try:
            # Step 1: Try with thumbnail first (fast and free)
            print(f"  Trying thumbnail first...")
            thumbnail_url = self.get_video_thumbnail_url(video_id)
            boss_name = self.identify_boss_from_images([thumbnail_url], game_name)

            if boss_name:
                print(f"  ✓ Identified boss from thumbnail: {boss_name}")
                return boss_name

            # Step 2: Thumbnail didn't work, extract actual video frames
            print(f"  Thumbnail didn't work, extracting frames from video...")
            frames = self.extract_video_frames(video_id)

            if not frames:
                print(f"  ✗ Could not extract frames from video")
                return None

            # Try to identify boss from extracted frames
            boss_name = self.identify_boss_from_images(frames, game_name)

            if boss_name:
                print(f"  ✓ Identified boss from video frames: {boss_name}")
                return boss_name
            else:
                print(f"  ✗ Could not identify boss even from video frames")
                return None

        except Exception as e:
            # If this is a retryable error and we haven't exceeded max retries
            if attempt < self.max_retries - 1:
                delay = exponential_backoff(attempt)
                print(f"  ⚠ Error: {e}")
                print(f"  Retrying in {delay:.1f} seconds (attempt {attempt + 1}/{self.max_retries})...")
                time.sleep(delay)
                return self.identify_boss(video_id, game_name, attempt + 1)
            else:
                print(f"  ✗ Failed after {self.max_retries} attempts: {e}")
                raise

    def format_title(self, game_name: str, boss_name: str) -> str:
        """Format the video title according to specifications"""
        is_souls = self.is_soulslike(game_name)

        if is_souls:
            return f"{game_name}: {boss_name} Melee PS5"
        else:
            return f"{game_name}: {boss_name} PS5"

    def update_video_title(self, video_id: str, new_title: str) -> bool:
        """Update the video title on YouTube"""
        try:
            # Get current video details
            video_response = self.youtube.videos().list(
                part='snippet',
                id=video_id
            ).execute()

            if not video_response.get('items'):
                print(f"  ✗ Video {video_id} not found")
                return False

            video = video_response['items'][0]
            snippet = video['snippet']

            # Update title
            snippet['title'] = new_title

            # Update video
            self.youtube.videos().update(
                part='snippet',
                body={
                    'id': video_id,
                    'snippet': snippet
                }
            ).execute()

            print(f"  ✓ Title updated to: {new_title}")
            return True

        except Exception as e:
            print(f"  ✗ Error updating title: {e}")
            return False

    def get_or_create_playlist(self, game_name: str) -> Optional[str]:
        """Get existing playlist for game or create new one"""
        # Search for existing playlist
        playlists_response = self.youtube.playlists().list(
            part='snippet',
            mine=True,
            maxResults=50
        ).execute()

        for playlist in playlists_response.get('items', []):
            if playlist['snippet']['title'].lower() == game_name.lower():
                print(f"  ✓ Found existing playlist: {game_name}")
                return playlist['id']

        # Create new playlist
        try:
            playlist_response = self.youtube.playlists().insert(
                part='snippet,status',
                body={
                    'snippet': {
                        'title': game_name,
                        'description': f'PS5 gameplay videos for {game_name}'
                    },
                    'status': {
                        'privacyStatus': 'public'
                    }
                }
            ).execute()

            playlist_id = playlist_response['id']
            print(f"  ✓ Created new playlist: {game_name}")
            return playlist_id

        except Exception as e:
            print(f"  ✗ Error creating playlist: {e}")
            return None

    def add_video_to_playlist(self, video_id: str, playlist_id: str) -> bool:
        """Add video to playlist"""
        try:
            self.youtube.playlistItems().insert(
                part='snippet',
                body={
                    'snippet': {
                        'playlistId': playlist_id,
                        'resourceId': {
                            'kind': 'youtube#video',
                            'videoId': video_id
                        }
                    }
                }
            ).execute()

            print(f"  ✓ Added to playlist")
            return True

        except Exception as e:
            # Check if video is already in playlist
            if 'videoAlreadyInPlaylist' in str(e):
                print(f"  ℹ Video already in playlist")
                return True
            print(f"  ✗ Error adding to playlist: {e}")
            return False

    def process_video(self, video: Dict, force: bool = False) -> bool:
        """Process a single video with database tracking and error handling"""
        video_id = video['id']
        title = video['title']

        print(f"\nProcessing: {title} ({video_id})")

        # Check database for existing record
        db_record = self.db.get_video(video_id)

        # Check if already processed (unless force flag is set)
        if not force:
            if video_id in self.processed_videos:
                print("  ⊘ Already processed (in sheets), skipping (use --force to reprocess)")
                return False

            if db_record and db_record['status'] == 'completed':
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
            self.db.add_video(video_id, title, game_name, status='pending')

        # Mark as processing
        self.db.update_video_status(video_id, 'processing')

        try:
            # Identify boss
            boss_name = self.identify_boss(video_id, game_name)
            if not boss_name:
                print("  ⊘ Could not identify boss")
                self.db.update_video_status(
                    video_id, 'failed',
                    error_message='Could not identify boss from video'
                )
                return False

            # Format new title
            new_title = self.format_title(game_name, boss_name)

            # Store original title for logging
            original_title = title

            # Update title
            if not self.update_video_title(video_id, new_title):
                self.db.update_video_status(
                    video_id, 'failed',
                    error_message='Failed to update video title'
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
                playlist_id=playlist_id
            )

            # Mark as completed in database
            self.db.update_video_status(
                video_id, 'completed',
                new_title=new_title,
                boss_name=boss_name
            )

            # Add to processed set
            self.processed_videos.add(video_id)

            return True

        except Exception as e:
            print(f"  ✗ Error processing video: {e}")
            self.db.update_video_status(
                video_id, 'failed',
                error_message=str(e)
            )
            return False

    def list_games(self):
        """List all detected games with video counts"""
        print("Fetching videos...")
        videos = self.get_my_videos()

        # Group by game name
        game_counts = defaultdict(int)
        ps5_videos = 0

        for video in videos:
            if self.is_default_ps5_title(video['title']):
                ps5_videos += 1
                game_name = self.extract_game_name(video['title'])
                game_counts[game_name] += 1

        print(f"\nFound {ps5_videos} videos with default PS5 titles")
        print("\nDetected games:")
        print("-" * 50)

        # Sort by count descending
        for game_name, count in sorted(game_counts.items(), key=lambda x: x[1], reverse=True):
            souls_tag = " [SOULS-LIKE]" if self.is_soulslike(game_name) else ""
            print(f"  {game_name}: {count} video(s){souls_tag}")

    def run(self, dry_run: bool = False, video_id: Optional[str] = None,
            game: Optional[str] = None, limit: Optional[int] = None, force: bool = False,
            resume: bool = False):
        """Main execution function"""
        # Print header
        console.print()
        console.print(Panel(
            f"[bold cyan]YouTube Boss Title Updater[/bold cyan]\n[dim]Version {__version__}[/dim]",
            border_style="cyan",
            box=box.DOUBLE
        ))

        # Clear any stuck 'processing' status from previous runs
        if not dry_run:
            self.db.clear_processing_status()

        # Show database statistics
        if not dry_run:
            stats = self.db.get_statistics()
            if stats.get('total', 0) > 0:
                console.print("\n[bold]Database Status:[/bold]")
                table = Table(show_header=False, box=None, padding=(0, 2))
                table.add_column("Label", style="cyan")
                table.add_column("Value", justify="right")

                table.add_row("Total tracked", str(stats.get('total', 0)))
                table.add_row("Completed", f"[green]{stats.get('completed', 0)}[/green]")
                table.add_row("Failed", f"[red]{stats.get('failed', 0)}[/red]")
                table.add_row("Pending", f"[yellow]{stats.get('pending', 0)}[/yellow]")

                console.print(table)

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
                videos_to_process.append({
                    'id': record['video_id'],
                    'title': record['original_title'],
                    'published_at': ''
                })

            if videos_to_process:
                console.print(f"[cyan]Found {len(videos_to_process)} videos to resume[/cyan]\n")
                self._process_video_list(videos_to_process, dry_run, force)
            else:
                console.print("[yellow]No videos to resume[/yellow]")
            return

        # Get all videos
        console.print("\n[bold]Fetching videos...[/bold]")
        videos = self.get_my_videos()
        console.print(f"[cyan]Found {len(videos)} total videos[/cyan]")

        # Filter for specific video ID if provided
        if video_id:
            videos = [v for v in videos if v['id'] == video_id]
            if not videos:
                console.print(f"\n[red]Error: Video ID {video_id} not found![/red]")
                return
            console.print(f"[cyan]Processing specific video: {video_id}[/cyan]")

        # Filter for default PS5 titles
        ps5_videos = [v for v in videos if self.is_default_ps5_title(v['title'])]
        console.print(f"[cyan]Found {len(ps5_videos)} videos with default PS5 titles[/cyan]")

        # Filter by game name if provided
        if game:
            ps5_videos = [v for v in ps5_videos if game.lower() in self.extract_game_name(v['title']).lower()]
            console.print(f"[cyan]Filtered to {len(ps5_videos)} videos matching game '{game}'[/cyan]")

        # Apply limit if provided
        if limit and limit > 0:
            ps5_videos = ps5_videos[:limit]
            console.print(f"[cyan]Limited to {len(ps5_videos)} videos[/cyan]")

        if not ps5_videos:
            console.print("\n[yellow]No videos to process![/yellow]")
            return

        self._process_video_list(ps5_videos, dry_run, force)

    def _estimate_cost(self, num_videos: int) -> Dict[str, float]:
        """
        Estimate processing costs

        Rough estimates:
        - Thumbnail analysis: $0.002 per video (1 image, gpt-4o)
        - Frame extraction: $0.010 per video (5 images, gpt-4o) if thumbnail fails
        - Assume 50% need frame extraction
        """
        thumbnail_cost = num_videos * 0.002
        frame_cost = num_videos * 0.5 * 0.010
        total_cost = thumbnail_cost + frame_cost

        return {
            'thumbnail': thumbnail_cost,
            'frame_extraction': frame_cost,
            'total': total_cost,
            'per_video': total_cost / num_videos if num_videos > 0 else 0
        }

    def _show_cost_estimate(self, num_videos: int):
        """Display cost estimate in a nice table"""
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

    def _process_video_list(self, videos: List[Dict], dry_run: bool, force: bool):
        """Process a list of videos with rich progress bar"""
        if dry_run:
            console.print("\n[yellow][DRY RUN MODE - No changes will be made][/yellow]\n")

        # Show cost estimate
        if not dry_run:
            self._show_cost_estimate(len(videos))

        # Process each video
        processed = 0
        failed = 0
        skipped = 0
        rate_limit = self.config.get('youtube.rate_limit_delay', 2)

        # Create progress bar
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeRemainingColumn(),
            console=console
        ) as progress:

            task = progress.add_task(
                f"[cyan]Processing videos...",
                total=len(videos)
            )

            for i, video in enumerate(videos, 1):
                video_title = video['title'][:50] + "..." if len(video['title']) > 50 else video['title']
                progress.update(task, description=f"[cyan]Processing: {video_title}")

                if dry_run:
                    console.print(f"\n[dim][{i}/{len(videos)}][/dim] [yellow][DRY RUN][/yellow] Would process: {video['title']}")
                    game_name = self.extract_game_name(video['title'])
                    console.print(f"  Game: {game_name}")
                    console.print(f"  Souls-like: {self.is_soulslike(game_name)}")
                else:
                    result = self.process_video(video, force=force)
                    if result:
                        processed += 1
                        console.print(f"[green]✓[/green] Processed successfully", style="dim")
                    elif result is False:
                        # Check if it was skipped or failed
                        video_id = video['id']
                        db_record = self.db.get_video(video_id)
                        if db_record and db_record['status'] == 'failed':
                            failed += 1
                            console.print(f"[red]✗[/red] Failed", style="dim")
                        else:
                            skipped += 1
                            console.print(f"[yellow]⊘[/yellow] Skipped", style="dim")

                    # Rate limiting
                    if i < len(videos):  # Don't sleep after last video
                        time.sleep(rate_limit)

                progress.update(task, advance=1)

        # Print summary
        self._print_summary(len(videos), processed, failed, skipped, dry_run)

    def _print_summary(self, total: int, processed: int, failed: int, skipped: int, dry_run: bool):
        """Print processing summary with rich formatting"""
        console.print()

        if dry_run:
            console.print(Panel(
                f"[yellow]Would process {total} videos[/yellow]",
                title="Dry Run Summary",
                border_style="yellow"
            ))
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

            table2.add_row("[green]Completed[/green]", str(stats.get('completed', 0)))
            table2.add_row("[red]Failed[/red]", str(stats.get('failed', 0)))
            table2.add_row("[yellow]Pending[/yellow]", str(stats.get('pending', 0)))
            table2.add_row("[cyan]Total[/cyan]", str(stats.get('total', 0)), style="bold")

            console.print(table2)
            console.print()


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='YouTube Boss Title Updater - Automatically update PS5 game videos with boss names',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  %(prog)s --dry-run                      # Preview changes without applying
  %(prog)s --video-id abc123 --force      # Process specific video
  %(prog)s --game "Bloodborne" --limit 5  # Process 5 Bloodborne videos
  %(prog)s --list-games                   # Show all detected games
  %(prog)s --config prod.yml              # Use custom config file
        '''
    )

    parser.add_argument(
        '--version',
        action='version',
        version=f'%(prog)s {__version__}'
    )

    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview what would be done without making changes'
    )

    parser.add_argument(
        '--config',
        type=str,
        metavar='PATH',
        help='Path to custom configuration file (default: use built-in config)'
    )

    parser.add_argument(
        '--video-id',
        type=str,
        metavar='ID',
        help='Process only this specific video ID'
    )

    parser.add_argument(
        '--game',
        type=str,
        metavar='NAME',
        help='Filter videos by game name (case-insensitive partial match)'
    )

    parser.add_argument(
        '--limit',
        type=int,
        metavar='N',
        help='Process only N videos (after filtering)'
    )

    parser.add_argument(
        '--force',
        action='store_true',
        help='Reprocess videos that have already been processed'
    )

    parser.add_argument(
        '--list-games',
        action='store_true',
        help='List all detected games with video counts and exit'
    )

    parser.add_argument(
        '--resume',
        action='store_true',
        help='Resume processing pending and failed videos from database'
    )

    args = parser.parse_args()

    # Load configuration
    try:
        config = Config(config_path=args.config)
        config.validate()
    except FileNotFoundError as e:
        print(f"Error: {e}")
        return 1
    except ValueError as e:
        print(f"Configuration Error: {e}")
        return 1

    # Create updater
    updater = YouTubeBossUpdater(config)

    # Authenticate first
    try:
        updater.authenticate_youtube()
    except Exception as e:
        print(f"Authentication failed: {e}")
        return 1

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
            resume=args.resume
        )
    except KeyboardInterrupt:
        print("\n\nProcess interrupted by user")
        return 130
    except Exception as e:
        print(f"\nError during execution: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == '__main__':
    exit(main())
