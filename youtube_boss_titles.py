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
from typing import List, Dict, Optional, Tuple
from datetime import datetime
from pathlib import Path
import time

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import openai
import requests
from PIL import Image
import yt_dlp


# YouTube API scopes
SCOPES = ['https://www.googleapis.com/auth/youtube.force-ssl']

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
    def __init__(self, openai_api_key: str):
        """Initialize the updater with API credentials"""
        self.youtube = None
        self.openai_client = openai.OpenAI(api_key=openai_api_key)

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
        return any(souls_game in game_lower for souls_game in SOULSLIKE_GAMES)

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
            # Default timestamps: 10s, 20s, 30s, 45s, 60s
            timestamps = [10, 20, 30, 45, 60]

        print(f"  Extracting frames from video at timestamps: {timestamps}")

        frames = []
        temp_dir = tempfile.mkdtemp()

        try:
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            video_path = os.path.join(temp_dir, 'video.mp4')

            # Download first 90 seconds of video
            ydl_opts = {
                'format': 'worst[ext=mp4]',  # Use worst quality for speed
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
            response = self.openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": content}],
                max_tokens=100
            )

            boss_name = response.choices[0].message.content.strip()

            if boss_name and boss_name != "Unknown Boss":
                return boss_name
            else:
                return None

        except Exception as e:
            print(f"  ✗ Error calling OpenAI API: {e}")
            return None

    def identify_boss(self, video_id: str, game_name: str) -> Optional[str]:
        """
        Use OpenAI Vision to identify the boss in the video
        Hybrid approach: Try thumbnail first, then extract video frames if needed
        """
        print(f"  Analyzing video {video_id} for boss identification...")

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

    def process_video(self, video: Dict) -> bool:
        """Process a single video"""
        video_id = video['id']
        title = video['title']

        print(f"\nProcessing: {title} ({video_id})")

        # Check if it's a default PS5 title
        if not self.is_default_ps5_title(title):
            print("  ⊘ Not a default PS5 title, skipping")
            return False

        # Extract game name
        game_name = self.extract_game_name(title)
        print(f"  Game: {game_name}")

        # Identify boss
        boss_name = self.identify_boss(video_id, game_name)
        if not boss_name:
            print("  ⊘ Could not identify boss, skipping")
            return False

        # Format new title
        new_title = self.format_title(game_name, boss_name)

        # Update title
        if not self.update_video_title(video_id, new_title):
            return False

        # Get or create playlist
        playlist_id = self.get_or_create_playlist(game_name)
        if playlist_id:
            self.add_video_to_playlist(video_id, playlist_id)

        return True

    def run(self, dry_run: bool = False):
        """Main execution function"""
        print("YouTube Boss Title Updater")
        print("=" * 50)

        # Authenticate
        self.authenticate_youtube()

        # Get all videos
        print("\nFetching videos...")
        videos = self.get_my_videos()
        print(f"Found {len(videos)} total videos")

        # Filter for default PS5 titles
        ps5_videos = [v for v in videos if self.is_default_ps5_title(v['title'])]
        print(f"Found {len(ps5_videos)} videos with default PS5 titles")

        if not ps5_videos:
            print("\nNo videos to process!")
            return

        if dry_run:
            print("\n[DRY RUN MODE - No changes will be made]")

        # Process each video
        processed = 0
        for video in ps5_videos:
            if dry_run:
                print(f"\n[DRY RUN] Would process: {video['title']}")
            else:
                if self.process_video(video):
                    processed += 1
                # Rate limiting
                time.sleep(2)

        print(f"\n{'Would process' if dry_run else 'Successfully processed'} {processed}/{len(ps5_videos)} videos")


def main():
    """Main entry point"""
    # Load API keys from environment or config
    openai_api_key = os.getenv('OPENAI_API_KEY')

    if not openai_api_key:
        print("Error: OPENAI_API_KEY environment variable not set")
        print("Please set it with: export OPENAI_API_KEY='your-key-here'")
        return

    # Create updater
    updater = YouTubeBossUpdater(openai_api_key)

    # Run with dry_run=True first to test
    # updater.run(dry_run=True)

    # Run for real
    updater.run(dry_run=False)


if __name__ == '__main__':
    main()
