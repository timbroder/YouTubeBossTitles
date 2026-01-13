# YouTube Boss Title Updater

[![Tests](https://github.com/timbroder/YouTubeBossTitles/workflows/Tests/badge.svg)](https://github.com/timbroder/YouTubeBossTitles/actions)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)

Automatically updates PS5 game video titles with boss names using AI vision analysis.

## Features

- Detects videos with default PS5 titles (e.g., `Bloodborne_20250321184741`)
- Hybrid boss identification: tries thumbnail first, then extracts video frames if needed
- Uses OpenAI GPT-4 Vision to identify boss names from multiple frames
- Updates titles to format: `[Game Name]: [Boss Name] PS5`
- Adds "Melee" tag for souls-like games: `[Game Name]: [Boss Name] Melee PS5`
- Automatically organizes videos into game-specific playlists
- Logs all changes to a Google Sheet with original title, new title, playlist info, and direct links

## Prerequisites

- Python 3.8 or higher
- ffmpeg installed on your system (for video frame extraction)
- YouTube channel with videos
- Google Cloud account (for YouTube API and Google Sheets)
- Google Drive (for storing the log spreadsheet)
- OpenAI account with API access

## Setup Instructions

### 1. Install ffmpeg

The script requires ffmpeg to extract frames from videos.

**Linux (Ubuntu/Debian):**
```bash
sudo apt update
sudo apt install ffmpeg
```

**Mac:**
```bash
brew install ffmpeg
```

**Windows:**
Download from [ffmpeg.org](https://ffmpeg.org/download.html) and add to PATH

### 2. Install Python Dependencies

```bash
pip install -r requirements.txt
```

### 3. Set Up YouTube API Credentials

#### Step 1: Create a Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Click "Select a project" → "New Project"
3. Enter project name (e.g., "YouTube Boss Updater")
4. Click "Create"

#### Step 2: Enable Required APIs

1. In your project, go to "APIs & Services" → "Library"
2. Search for "YouTube Data API v3"
3. Click on it and press "Enable"
4. Go back to "Library"
5. Search for "Google Sheets API"
6. Click on it and press "Enable"

#### Step 3: Create OAuth 2.0 Credentials

1. Go to "APIs & Services" → "Credentials"
2. Click "Create Credentials" → "OAuth client ID"
3. If prompted, configure the OAuth consent screen:
   - User Type: "External"
   - App name: "YouTube Boss Updater"
   - User support email: your email
   - Developer contact: your email
   - Click "Save and Continue"
   - Scopes: Skip (click "Save and Continue")
   - Test users: Add your Google account email
   - Click "Save and Continue"
4. Back to creating OAuth client ID:
   - Application type: "Desktop app"
   - Name: "YouTube Boss Updater Desktop"
   - Click "Create"
5. Click "Download JSON"
6. Rename the downloaded file to `client_secret.json`
7. Move `client_secret.json` to this project directory

### 4. Set Up OpenAI API Key

#### Step 1: Get API Key

1. Go to [OpenAI Platform](https://platform.openai.com/)
2. Sign in or create an account
3. Go to "API Keys" section
4. Click "Create new secret key"
5. Copy the key (you won't be able to see it again!)

#### Step 2: Set Environment Variable

**Linux/Mac:**
```bash
export OPENAI_API_KEY='your-api-key-here'
```

**Windows (Command Prompt):**
```cmd
set OPENAI_API_KEY=your-api-key-here
```

**Windows (PowerShell):**
```powershell
$env:OPENAI_API_KEY="your-api-key-here"
```

Or create a `.env` file in the project directory:
```
OPENAI_API_KEY=your-api-key-here
```

## Usage

### First Run (Dry Run)

Test the script without making changes:

```python
# Edit youtube_boss_titles.py, change the last line in main() to:
updater.run(dry_run=True)
```

Then run:
```bash
python youtube_boss_titles.py
```

### Normal Run

Process and update videos:

```bash
python youtube_boss_titles.py
```

On first run, a browser window will open asking you to authorize the app. After authorization, the credentials will be saved in `token.json` for future use.

## How It Works

1. **Authentication**: Connects to YouTube and Google Sheets using OAuth 2.0
2. **Log Setup**: Creates or opens a Google Sheet named "YouTube Boss Title Updates"
3. **Video Discovery**: Fetches all videos from your channel
4. **Title Detection**: Identifies videos with default PS5 titles using regex pattern
5. **Game Extraction**: Extracts game name from the title
6. **Boss Identification** (Hybrid Approach):
   - **Step 1**: Tries video thumbnail first (fast, no download needed)
   - **Step 2**: If thumbnail fails, downloads first 90 seconds of video using yt-dlp
   - **Step 3**: Extracts frames at 10s, 20s, 30s, 45s, and 60s using ffmpeg
   - **Step 4**: Sends frames to OpenAI GPT-4 Vision API
   - AI analyzes images to identify boss name from health bars, UI elements, boss intro screens
7. **Title Update**: Formats and updates the title with boss name
8. **Playlist Organization**: Adds video to game-specific playlist (creates if needed)
9. **Logging**: Records all changes to Google Sheet with:
   - Timestamp
   - Original title
   - New title
   - Playlist name
   - Direct link to video
   - Direct link to playlist

## Title Formats

**Regular Games:**
```
Clair Obscur: Expedition 33: Final Boss PS5
```

**Souls-like Games (automatically detected):**
```
Bloodborne: Father Gascoigne Melee PS5
```

Souls-like games include:
- Bloodborne
- Dark Souls series
- Demon's Souls
- Elden Ring
- Sekiro
- Lords of the Fallen
- Lies of P
- Nioh series
- And more...

## Configuration

### Adding More Souls-like Games

Edit the `SOULSLIKE_GAMES` list in `youtube_boss_titles.py`:

```python
SOULSLIKE_GAMES = [
    'bloodborne',
    'dark souls',
    # Add more games here
    'your game name',
]
```

### Rate Limiting

The script includes a 2-second delay between processing videos to respect API rate limits. Adjust in the `run()` method:

```python
time.sleep(2)  # Change to desired delay in seconds
```

### Google Sheets Logging

The script automatically creates a Google Sheet named "YouTube Boss Title Updates" to log all changes.

**Spreadsheet Columns:**
- **Timestamp**: When the change was made
- **Original Title**: The default PS5 title before changes
- **New Title**: The updated title with boss name
- **Playlist Name**: The game playlist it was added to
- **Video Link**: Direct link to the video on YouTube
- **Playlist Link**: Direct link to the playlist

**Customizing the spreadsheet name:**
```python
updater = YouTubeBossUpdater(
    openai_api_key=openai_api_key,
    log_spreadsheet_name="My Custom Log Name"
)
```

The spreadsheet will be created in your Google Drive and can be shared with others for review.

## Troubleshooting

### "client_secret.json not found"
- Make sure you downloaded the OAuth credentials from Google Cloud Console
- Rename the file to exactly `client_secret.json`
- Place it in the same directory as the script

### "OPENAI_API_KEY environment variable not set"
- Set the environment variable before running the script
- Or create a `.env` file with the key

### "Quota exceeded" errors
- YouTube API has daily quotas
- Check your quota usage in Google Cloud Console
- Consider requesting a quota increase

### Boss identification not accurate
- The script tries thumbnails first, then automatically extracts video frames
- You can customize frame extraction timestamps by modifying the `timestamps` parameter in `extract_video_frames()`
- Default timestamps are: 10s, 20s, 30s, 45s, 60s

### ffmpeg not found
- Make sure ffmpeg is installed and available in your PATH
- Test with: `ffmpeg -version`
- See installation instructions above

## Testing

The project includes comprehensive unit and integration tests.

### Running Tests

**Run all tests:**
```bash
pytest
```

**Run with coverage report:**
```bash
pytest --cov=youtube_boss_titles --cov-report=html
```

**Run specific test classes:**
```bash
pytest test_youtube_boss_titles.py::TestTitleDetection -v
pytest test_youtube_boss_titles.py::TestBossIdentification -v
```

**Run specific test:**
```bash
pytest test_youtube_boss_titles.py::TestTitleDetection::test_is_default_ps5_title_valid -v
```

### Test Coverage

The test suite includes:

**Unit Tests:**
- Title detection and parsing (PS5 title pattern matching)
- Game name extraction
- Souls-like game detection
- Title formatting for regular and souls-like games
- Authentication flows
- Video thumbnail URL generation
- Frame extraction from videos
- Boss identification from images
- Playlist management (create/get)
- Google Sheets logging
- Video title updates

**Integration Tests:**
- Full video processing workflow
- End-to-end authentication and API calls
- Dry run mode validation
- Error handling and edge cases

**Mocked Components:**
- YouTube Data API
- Google Sheets API
- OpenAI API
- yt-dlp video downloads
- ffmpeg frame extraction
- OAuth authentication

### Viewing Coverage Report

After running tests with coverage, open the HTML report:

```bash
# Linux/Mac
open htmlcov/index.html

# Windows
start htmlcov/index.html
```

### Test Structure

```
test_youtube_boss_titles.py
├── Fixtures (shared test data and mocks)
├── Unit Tests
│   ├── TestTitleDetection
│   ├── TestTitleFormatting
│   ├── TestAuthentication
│   ├── TestVideoOperations
│   ├── TestBossIdentification
│   ├── TestPlaylistManagement
│   ├── TestSheetsLogging
│   └── TestVideoTitleUpdate
├── Integration Tests
│   └── TestIntegration
└── Edge Cases
    └── TestEdgeCases
```

## Future Enhancements

Potential improvements:
- Scrape boss lists from gaming wikis for better AI context
- Add support for custom game-to-playlist mappings
- Batch processing with progress bars
- Backup original titles before updating
- Support for custom title templates
- Configurable frame extraction timestamps per game
- Support for analyzing longer videos (currently limited to first 90 seconds)

## Costs

- **YouTube API**: Free tier includes 10,000 quota units per day (sufficient for most users)
- **OpenAI API**:
  - Thumbnail-only identification: ~$0.01 per video
  - With frame extraction: ~$0.03-0.05 per video (5 frames analyzed)
  - Most videos will try thumbnail first, only downloading if needed

## License

MIT

## Support

For issues or questions, please open an issue on GitHub.