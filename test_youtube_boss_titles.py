"""
Unit and Integration Tests for YouTube Boss Title Updater
"""

from unittest.mock import Mock, patch

import pytest

from config import Config
from youtube_boss_titles import YouTubeBossUpdater

# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def mock_config():
    """Provide a mock Config object"""
    config = Config()
    # Override API key for testing
    config.config["openai"]["api_key"] = "test-openai-key-12345"
    return config


@pytest.fixture
def updater(mock_config):
    """Create a YouTubeBossUpdater instance with mocked OpenAI client"""
    with patch("youtube_boss_titles.openai.OpenAI"), patch("youtube_boss_titles.VideoDatabase"):
        # Create a mock logger
        import logging

        mock_logger = logging.getLogger("test_logger")
        return YouTubeBossUpdater(config=mock_config, logger_instance=mock_logger, db_path=":memory:")


@pytest.fixture
def mock_credentials():
    """Mock Google OAuth credentials"""
    mock_creds = Mock()
    mock_creds.valid = True
    mock_creds.expired = False
    mock_creds.to_json.return_value = '{"token": "mock_token"}'
    return mock_creds


@pytest.fixture
def mock_youtube_service():
    """Mock YouTube API service"""
    mock_service = Mock()
    return mock_service


@pytest.fixture
def mock_sheets_client():
    """Mock Google Sheets client"""
    mock_client = Mock()
    return mock_client


@pytest.fixture
def sample_ps5_videos():
    """Sample PS5 video data"""
    return [
        {"id": "video1", "title": "Bloodborne_20250321184741", "published_at": "2025-03-21T18:47:41Z"},
        {"id": "video2", "title": "Clair Obscur: Expedition 33_20250629134801", "published_at": "2025-06-29T13:48:01Z"},
        {"id": "video3", "title": "Regular Video Title", "published_at": "2025-01-01T00:00:00Z"},
    ]


# ============================================================================
# UNIT TESTS - Title Detection and Parsing
# ============================================================================


class TestTitleDetection:
    """Test PS5 title detection and parsing"""

    def test_is_default_ps5_title_valid(self, updater):
        """Test detection of valid PS5 default titles"""
        assert updater.is_default_ps5_title("Bloodborne_20250321184741") is True
        assert updater.is_default_ps5_title("Game Name_20250101000000") is True
        assert updater.is_default_ps5_title("Clair Obscur: Expedition 33_20250629134801") is True

    def test_is_default_ps5_title_invalid(self, updater):
        """Test rejection of non-PS5 titles"""
        assert updater.is_default_ps5_title("Regular Video Title") is False
        assert updater.is_default_ps5_title("Game_123") is False
        assert updater.is_default_ps5_title("") is False
        assert updater.is_default_ps5_title("NoUnderscore20250321184741") is False

    def test_extract_game_name(self, updater):
        """Test game name extraction from PS5 titles"""
        assert updater.extract_game_name("Bloodborne_20250321184741") == "Bloodborne"
        assert updater.extract_game_name("Dark Souls III_20250101000000") == "Dark Souls III"
        assert updater.extract_game_name("Clair Obscur: Expedition 33_20250629134801") == "Clair Obscur: Expedition 33"

    def test_is_soulslike(self, updater):
        """Test souls-like game detection"""
        assert updater.is_soulslike("Bloodborne") is True
        assert updater.is_soulslike("Dark Souls III") is True
        assert updater.is_soulslike("Elden Ring") is True
        assert updater.is_soulslike("Sekiro: Shadows Die Twice") is True
        assert updater.is_soulslike("Clair Obscur: Expedition 33") is False
        assert updater.is_soulslike("God of War") is False


# ============================================================================
# UNIT TESTS - Title Formatting
# ============================================================================


class TestTitleFormatting:
    """Test video title formatting"""

    def test_format_title_regular_game(self, updater):
        """Test title formatting for regular games"""
        result = updater.format_title("Clair Obscur: Expedition 33", "Final Boss")
        assert result == "Clair Obscur: Expedition 33: Final Boss PS5"

    def test_format_title_soulslike_game(self, updater):
        """Test title formatting for souls-like games"""
        result = updater.format_title("Bloodborne", "Father Gascoigne")
        assert result == "Bloodborne: Father Gascoigne Melee PS5"

        result = updater.format_title("Elden Ring", "Malenia")
        assert result == "Elden Ring: Malenia Melee PS5"


# ============================================================================
# UNIT TESTS - Authentication
# ============================================================================


class TestAuthentication:
    """Test authentication flows"""

    @patch("youtube_boss_titles.os.path.exists")
    @patch("youtube_boss_titles.Credentials.from_authorized_user_file")
    @patch("youtube_boss_titles.build")
    @patch("youtube_boss_titles.gspread.authorize")
    def test_authenticate_with_existing_token(
        self, mock_gspread, mock_build, mock_creds_from_file, mock_exists, updater, mock_credentials
    ):
        """Test authentication with existing valid token"""
        mock_exists.return_value = True
        mock_creds_from_file.return_value = mock_credentials
        mock_build.return_value = Mock()
        mock_gspread.return_value = Mock()

        updater.authenticate_youtube()

        assert updater.youtube is not None
        assert updater.sheets_client is not None
        mock_creds_from_file.assert_called_once()
        mock_build.assert_called_once()
        mock_gspread.assert_called_once()

    @patch("youtube_boss_titles.os.path.exists")
    @patch("youtube_boss_titles.InstalledAppFlow.from_client_secrets_file")
    @patch("youtube_boss_titles.build")
    @patch("youtube_boss_titles.gspread.authorize")
    @patch("builtins.open", create=True)
    def test_authenticate_without_token(
        self, mock_open, mock_gspread, mock_build, mock_flow, mock_exists, updater, mock_credentials
    ):
        """Test authentication flow when no token exists"""
        # First call checks token.json (doesn't exist), second checks client_secret.json (exists)
        mock_exists.side_effect = [False, True]

        mock_flow_instance = Mock()
        mock_flow_instance.run_local_server.return_value = mock_credentials
        mock_flow.return_value = mock_flow_instance

        mock_build.return_value = Mock()
        mock_gspread.return_value = Mock()

        updater.authenticate_youtube()

        assert updater.youtube is not None
        assert updater.sheets_client is not None
        mock_flow.assert_called_once()
        mock_flow_instance.run_local_server.assert_called_once()


# ============================================================================
# UNIT TESTS - Video Operations
# ============================================================================


class TestVideoOperations:
    """Test video-related operations"""

    def test_get_video_thumbnail_url(self, updater):
        """Test thumbnail URL generation"""
        url = updater.get_video_thumbnail_url("test_video_id")
        assert url == "https://img.youtube.com/vi/test_video_id/maxresdefault.jpg"

    @patch("youtube_boss_titles.tempfile.mkdtemp")
    @patch("youtube_boss_titles.yt_dlp.YoutubeDL")
    @patch("youtube_boss_titles.subprocess.run")
    @patch("youtube_boss_titles.os.path.exists")
    @patch("builtins.open", create=True)
    @patch("youtube_boss_titles.base64.b64encode")
    def test_extract_video_frames_success(
        self, mock_b64, mock_open, mock_exists, mock_subprocess, mock_ytdl, mock_mkdtemp, updater
    ):
        """Test successful video frame extraction"""
        mock_mkdtemp.return_value = "/tmp/test"
        mock_exists.side_effect = [True, True, True]  # video exists, frames exist
        mock_b64.return_value.decode.return_value = "base64encodedimage"

        mock_ytdl_instance = Mock()
        mock_ytdl.return_value.__enter__.return_value = mock_ytdl_instance
        mock_subprocess.return_value = Mock()

        frames = updater.extract_video_frames("test_video_id", timestamps=[10, 20])

        assert len(frames) == 2
        assert all(frame.startswith("data:image/jpeg;base64,") for frame in frames)

    def test_get_my_videos(self, updater, sample_ps5_videos):
        """Test fetching videos from channel"""
        mock_youtube = Mock()

        # Mock channels().list() response
        mock_channels_response = {"items": [{"contentDetails": {"relatedPlaylists": {"uploads": "UU_playlist_id"}}}]}

        # Mock playlistItems().list() response
        mock_playlist_response = {
            "items": [
                {"snippet": {"resourceId": {"videoId": v["id"]}, "title": v["title"], "publishedAt": v["published_at"]}}
                for v in sample_ps5_videos
            ]
        }

        mock_youtube.channels().list().execute.return_value = mock_channels_response
        mock_youtube.playlistItems().list().execute.return_value = mock_playlist_response

        updater.youtube = mock_youtube

        videos = updater.get_my_videos()

        assert len(videos) == 3
        assert videos[0]["title"] == "Bloodborne_20250321184741"


# ============================================================================
# UNIT TESTS - Boss Identification
# ============================================================================


class TestBossIdentification:
    """Test boss identification logic"""

    def test_identify_boss_from_images_success(self, updater):
        """Test successful boss identification from images"""
        mock_response = Mock()
        mock_response.choices = [Mock(message=Mock(content="Father Gascoigne"))]

        updater.openai_client.chat.completions.create = Mock(return_value=mock_response)

        boss_name = updater.identify_boss_from_images(["http://example.com/image.jpg"], "Bloodborne")

        assert boss_name == "Father Gascoigne"
        updater.openai_client.chat.completions.create.assert_called_once()

    def test_identify_boss_from_images_unknown(self, updater):
        """Test boss identification when boss is unknown"""
        mock_response = Mock()
        mock_response.choices = [Mock(message=Mock(content="Unknown Boss"))]

        updater.openai_client.chat.completions.create = Mock(return_value=mock_response)

        boss_name = updater.identify_boss_from_images(["http://example.com/image.jpg"], "Some Game")

        assert boss_name is None

    def test_identify_boss_from_images_api_error(self, updater):
        """Test boss identification when API fails"""
        updater.openai_client.chat.completions.create = Mock(side_effect=Exception("API Error"))

        boss_name = updater.identify_boss_from_images(["http://example.com/image.jpg"], "Bloodborne")

        assert boss_name is None

    def test_identify_boss_thumbnail_success(self, updater):
        """Test boss identification using thumbnail (hybrid approach - first attempt)"""
        mock_response = Mock()
        mock_response.choices = [Mock(message=Mock(content="Cleric Beast"))]

        updater.openai_client.chat.completions.create = Mock(return_value=mock_response)
        updater.get_video_thumbnail_url = Mock(return_value="http://thumbnail.jpg")
        # Mock cache miss
        updater.db.get_cached_boss = Mock(return_value=None)

        boss_name = updater.identify_boss("video123", "Bloodborne")

        assert boss_name == "Cleric Beast"

    def test_identify_boss_fallback_to_frames(self, updater):
        """Test boss identification falling back to frame extraction"""
        # First call (thumbnail) returns None, second call (frames) succeeds
        mock_response_fail = Mock()
        mock_response_fail.choices = [Mock(message=Mock(content="Unknown Boss"))]

        mock_response_success = Mock()
        mock_response_success.choices = [Mock(message=Mock(content="Blood-starved Beast"))]

        updater.openai_client.chat.completions.create = Mock(side_effect=[mock_response_fail, mock_response_success])
        updater.get_video_thumbnail_url = Mock(return_value="http://thumbnail.jpg")
        updater.extract_video_frames = Mock(return_value=["frame1", "frame2"])
        # Mock cache miss
        updater.db.get_cached_boss = Mock(return_value=None)

        boss_name = updater.identify_boss("video123", "Bloodborne")

        assert boss_name == "Blood-starved Beast"
        assert updater.openai_client.chat.completions.create.call_count == 2


# ============================================================================
# UNIT TESTS - Playlist Management
# ============================================================================


class TestPlaylistManagement:
    """Test playlist operations"""

    def test_get_or_create_playlist_existing(self, updater):
        """Test getting an existing playlist"""
        mock_youtube = Mock()
        mock_playlists_response = {"items": [{"id": "playlist123", "snippet": {"title": "Bloodborne"}}]}

        mock_youtube.playlists().list().execute.return_value = mock_playlists_response
        updater.youtube = mock_youtube

        playlist_id = updater.get_or_create_playlist("Bloodborne")

        assert playlist_id == "playlist123"

    def test_get_or_create_playlist_new(self, updater):
        """Test creating a new playlist"""
        mock_youtube = Mock()

        # No existing playlists
        mock_playlists_response = {"items": []}
        mock_youtube.playlists().list().execute.return_value = mock_playlists_response

        # Create new playlist
        mock_create_response = {"id": "new_playlist456"}
        mock_youtube.playlists().insert().execute.return_value = mock_create_response

        updater.youtube = mock_youtube

        playlist_id = updater.get_or_create_playlist("Elden Ring")

        assert playlist_id == "new_playlist456"

    def test_add_video_to_playlist_success(self, updater):
        """Test adding video to playlist"""
        mock_youtube = Mock()
        mock_youtube.playlistItems().insert().execute.return_value = {}
        updater.youtube = mock_youtube

        result = updater.add_video_to_playlist("video123", "playlist456")

        assert result is True

    def test_add_video_to_playlist_already_exists(self, updater):
        """Test adding video that's already in playlist"""
        mock_youtube = Mock()
        mock_youtube.playlistItems().insert().execute.side_effect = Exception("videoAlreadyInPlaylist")
        updater.youtube = mock_youtube

        result = updater.add_video_to_playlist("video123", "playlist456")

        assert result is True  # Should still return True


# ============================================================================
# UNIT TESTS - Google Sheets Logging
# ============================================================================


class TestSheetsLogging:
    """Test Google Sheets logging"""

    @patch("youtube_boss_titles.gspread")
    def test_setup_log_spreadsheet_existing(self, mock_gspread_module, updater):
        """Test opening existing log spreadsheet"""
        mock_spreadsheet = Mock()
        mock_sheet = Mock()
        mock_spreadsheet.sheet1 = mock_sheet

        mock_sheets_client = Mock()
        mock_sheets_client.open.return_value = mock_spreadsheet
        updater.sheets_client = mock_sheets_client

        updater.setup_log_spreadsheet()

        assert updater.log_sheet == mock_sheet
        mock_sheets_client.open.assert_called_once_with("YouTube Boss Title Updates")

    def test_setup_log_spreadsheet_new(self, updater):
        """Test creating new log spreadsheet"""

        # Create a mock exception that inherits from Exception
        class MockSpreadsheetNotFoundError(Exception):
            pass

        mock_spreadsheet = Mock()
        mock_sheet = Mock()
        mock_spreadsheet.sheet1 = mock_sheet
        mock_spreadsheet.url = "https://docs.google.com/spreadsheets/test"

        mock_sheets_client = Mock()
        mock_sheets_client.open.side_effect = MockSpreadsheetNotFoundError
        mock_sheets_client.create.return_value = mock_spreadsheet
        updater.sheets_client = mock_sheets_client

        # Patch the exception in the actual code
        with patch("youtube_boss_titles.gspread.exceptions.SpreadsheetNotFound", MockSpreadsheetNotFoundError):
            updater.setup_log_spreadsheet()

        assert updater.log_sheet == mock_sheet
        mock_sheet.append_row.assert_called_once()
        mock_sheet.format.assert_called_once()

    def test_log_video_update(self, updater):
        """Test logging video update to spreadsheet"""
        mock_sheet = Mock()
        updater.log_sheet = mock_sheet

        updater.log_video_update(
            video_id="video123",
            original_title="Bloodborne_20250321184741",
            new_title="Bloodborne: Father Gascoigne Melee PS5",
            playlist_name="Bloodborne",
            playlist_id="playlist456",
        )

        mock_sheet.append_row.assert_called_once()
        call_args = mock_sheet.append_row.call_args[0][0]

        assert "Bloodborne_20250321184741" in call_args
        assert "Bloodborne: Father Gascoigne Melee PS5" in call_args
        assert "https://www.youtube.com/watch?v=video123" in call_args
        assert "https://www.youtube.com/playlist?list=playlist456" in call_args


# ============================================================================
# UNIT TESTS - Video Title Updates
# ============================================================================


class TestVideoTitleUpdate:
    """Test video title update operations"""

    def test_update_video_title_success(self, updater):
        """Test successful video title update"""
        mock_youtube = Mock()
        mock_video_response = {"items": [{"id": "video123", "snippet": {"title": "Old Title"}}]}

        mock_youtube.videos().list().execute.return_value = mock_video_response
        mock_youtube.videos().update().execute.return_value = {}
        updater.youtube = mock_youtube

        result = updater.update_video_title("video123", "New Title")

        assert result is True

    def test_update_video_title_not_found(self, updater):
        """Test updating video that doesn't exist"""
        mock_youtube = Mock()
        mock_youtube.videos().list().execute.return_value = {"items": []}
        updater.youtube = mock_youtube

        result = updater.update_video_title("nonexistent", "New Title")

        assert result is False


# ============================================================================
# INTEGRATION TESTS
# ============================================================================


class TestIntegration:
    """Integration tests for full workflows"""

    @patch("youtube_boss_titles.openai.OpenAI")
    @patch("youtube_boss_titles.VideoDatabase")
    def test_process_video_full_workflow(self, mock_db, mock_openai_class, mock_config):
        """Test full video processing workflow"""
        # Setup
        updater = YouTubeBossUpdater(config=mock_config, db_path=":memory:")

        # Mock YouTube API
        mock_youtube = Mock()
        mock_video_response = {"items": [{"id": "video123", "snippet": {"title": "Bloodborne_20250321184741"}}]}
        mock_youtube.videos().list().execute.return_value = mock_video_response
        mock_youtube.videos().update().execute.return_value = {}

        # Mock playlist operations
        mock_playlists_response = {"items": []}
        mock_youtube.playlists().list().execute.return_value = mock_playlists_response
        mock_youtube.playlists().insert().execute.return_value = {"id": "new_playlist"}
        mock_youtube.playlistItems().insert().execute.return_value = {}

        updater.youtube = mock_youtube

        # Mock OpenAI response
        mock_openai_instance = Mock()
        mock_response = Mock()
        mock_response.choices = [Mock(message=Mock(content="Father Gascoigne"))]
        mock_openai_instance.chat.completions.create.return_value = mock_response
        updater.openai_client = mock_openai_instance

        # Mock sheets logging
        mock_sheet = Mock()
        updater.log_sheet = mock_sheet

        # Execute
        video = {"id": "video123", "title": "Bloodborne_20250321184741", "published_at": "2025-03-21T18:47:41Z"}

        result = updater.process_video(video)

        # Verify
        assert result is True
        mock_youtube.videos().update().execute.assert_called_once()
        mock_youtube.playlists().insert().execute.assert_called_once()
        mock_sheet.append_row.assert_called_once()

    def test_process_video_skip_non_ps5_title(self, updater):
        """Test that non-PS5 titles are skipped"""
        video = {"id": "video123", "title": "Regular Video Title", "published_at": "2025-01-01T00:00:00Z"}

        result = updater.process_video(video)

        assert result is False

    @patch("youtube_boss_titles.openai.OpenAI")
    @patch("youtube_boss_titles.VideoDatabase")
    def test_process_video_skip_when_boss_not_identified(self, mock_db, mock_openai_class, mock_config):
        """Test that videos are skipped when boss can't be identified"""
        updater = YouTubeBossUpdater(config=mock_config, db_path=":memory:")

        # Mock OpenAI to return Unknown Boss
        mock_openai_instance = Mock()
        mock_response = Mock()
        mock_response.choices = [Mock(message=Mock(content="Unknown Boss"))]
        mock_openai_instance.chat.completions.create.return_value = mock_response
        updater.openai_client = mock_openai_instance

        # Mock frame extraction to return empty
        updater.extract_video_frames = Mock(return_value=[])

        video = {"id": "video123", "title": "Bloodborne_20250321184741", "published_at": "2025-03-21T18:47:41Z"}

        result = updater.process_video(video)

        assert result is False

    def test_run_dry_run_mode(self, updater, sample_ps5_videos):
        """Test dry run mode doesn't make changes"""
        # Mock authentication method
        updater.authenticate_youtube = Mock()
        updater.youtube = Mock()
        updater.sheets_client = Mock()

        # Mock get_my_videos
        updater.get_my_videos = Mock(return_value=sample_ps5_videos)

        # Run in dry run mode
        updater.run(dry_run=True)

        # Verify authentication was called
        updater.authenticate_youtube.assert_called_once()

        # Verify no sheets setup was called
        assert updater.log_sheet is None


# ============================================================================
# TEST EDGE CASES
# ============================================================================


class TestEdgeCases:
    """Test edge cases and error handling"""

    def test_extract_game_name_empty_string(self, updater):
        """Test extracting game name from empty string"""
        result = updater.extract_game_name("_20250321184741")
        assert result == ""

    def test_format_title_with_special_characters(self, updater):
        """Test title formatting with special characters"""
        result = updater.format_title("Game: Special Edition", "Boss & Enemy")
        assert result == "Game: Special Edition: Boss & Enemy PS5"

    def test_log_video_update_without_initialized_sheet(self, updater):
        """Test logging when sheet is not initialized"""
        updater.log_sheet = None

        # Should not raise exception
        updater.log_video_update(
            video_id="video123",
            original_title="Old Title",
            new_title="New Title",
            playlist_name="Game",
            playlist_id="playlist123",
        )

    def test_identify_boss_with_empty_frames(self, updater):
        """Test boss identification when frame extraction returns empty list"""
        mock_response = Mock()
        mock_response.choices = [Mock(message=Mock(content="Unknown Boss"))]
        updater.openai_client.chat.completions.create = Mock(return_value=mock_response)

        updater.extract_video_frames = Mock(return_value=[])
        # Mock cache miss
        updater.db.get_cached_boss = Mock(return_value=None)

        result = updater.identify_boss("video123", "Bloodborne")

        assert result is None


# ============================================================================
# SPRINT 2: LOGGING AND ERROR TRACKING TESTS
# ============================================================================


class TestLogging:
    """Tests for structured logging functionality"""

    def test_logger_initialization(self, updater):
        """Test that updater is initialized with a logger"""
        assert updater.logger is not None
        assert hasattr(updater.logger, "info")
        assert hasattr(updater.logger, "error")
        assert hasattr(updater.logger, "warning")

    def test_error_logging_in_process_video(self, updater):
        """Test that errors are logged when processing fails"""
        updater.is_default_ps5_title = Mock(return_value=True)
        updater.extract_game_name = Mock(return_value="TestGame")
        updater.identify_boss = Mock(side_effect=Exception("Test error"))
        updater.db = Mock()
        # First call returns None (not in DB yet), second call returns record with attempts
        updater.db.get_video = Mock(side_effect=[None, {"attempts": 1, "status": "processing"}])
        updater.db.add_video = Mock()
        updater.db.update_video_status = Mock()
        updater.log_error_to_sheet = Mock()

        video = {"id": "test123", "title": "TestGame_20240101120000"}

        result = updater.process_video(video, force=False)

        assert result is False
        updater.db.update_video_status.assert_called()
        updater.log_error_to_sheet.assert_called_once()


class TestErrorTracking:
    """Tests for enhanced error tracking to Google Sheets"""

    def test_error_sheet_setup(self, updater):
        """Test that error sheet is created during setup"""
        import gspread

        mock_spreadsheet = Mock()
        mock_sheet = Mock()
        mock_error_sheet = Mock()

        updater.sheets_client = Mock()
        updater.sheets_client.open = Mock(side_effect=gspread.exceptions.SpreadsheetNotFound("Not found"))
        updater.sheets_client.create = Mock(return_value=mock_spreadsheet)

        mock_spreadsheet.sheet1 = mock_sheet
        mock_spreadsheet.add_worksheet = Mock(return_value=mock_error_sheet)

        # Mock the _setup_error_sheet_headers method
        updater._setup_error_sheet_headers = Mock()

        updater.setup_log_spreadsheet()

        # Verify error sheet was created
        mock_spreadsheet.add_worksheet.assert_called_with(title="Errors", rows="1000", cols="10")
        assert updater.error_sheet == mock_error_sheet

    def test_log_error_to_sheet(self, updater):
        """Test logging errors to the Errors sheet"""
        mock_error_sheet = Mock()
        updater.error_sheet = mock_error_sheet

        updater.log_error_to_sheet(
            video_id="test123",
            video_title="Test Video",
            game_name="TestGame",
            error_type="test_error",
            error_message="Test error message",
            attempts=3,
        )

        # Verify append_row was called
        mock_error_sheet.append_row.assert_called_once()
        call_args = mock_error_sheet.append_row.call_args[0][0]

        # Verify row structure
        assert call_args[1] == "test123"  # video_id
        assert call_args[2] == "Test Video"  # video_title
        assert call_args[3] == "TestGame"  # game_name
        assert call_args[4] == "test_error"  # error_type
        assert call_args[5] == "Test error message"  # error_message
        assert call_args[6] == 3  # attempts
        assert "youtube.com/watch?v=test123" in call_args[7]  # video_link

    def test_log_error_to_sheet_truncates_long_messages(self, updater):
        """Test that long error messages are truncated"""
        mock_error_sheet = Mock()
        updater.error_sheet = mock_error_sheet

        long_message = "A" * 1000  # 1000 character message

        updater.log_error_to_sheet(
            video_id="test123",
            video_title="Test Video",
            game_name="TestGame",
            error_type="test_error",
            error_message=long_message,
            attempts=1,
        )

        call_args = mock_error_sheet.append_row.call_args[0][0]
        error_message = call_args[5]

        # Should be truncated to 500 chars + "..."
        assert len(error_message) <= 503
        assert error_message.endswith("...")

    def test_log_error_to_sheet_without_error_sheet(self, updater):
        """Test that logging errors handles missing error sheet gracefully"""
        updater.error_sheet = None
        updater.logger = Mock()

        # Should not raise exception
        updater.log_error_to_sheet(
            video_id="test123",
            video_title="Test Video",
            game_name="TestGame",
            error_type="test_error",
            error_message="Test error",
            attempts=1,
        )

        # Should log a warning
        updater.logger.warning.assert_called()


class TestErrorMessages:
    """Tests for better error messages functionality"""

    def test_format_error_with_code(self):
        """Test error message formatting"""
        from error_messages import ErrorCode, format_error

        error_msg = format_error(ErrorCode.CONFIG_NOT_FOUND)

        assert ErrorCode.CONFIG_NOT_FOUND in error_msg
        assert "Configuration file not found" in error_msg
        assert "💡 Hint:" in error_msg

    def test_format_error_with_details(self):
        """Test error message formatting with details"""
        from error_messages import ErrorCode, format_error

        error_msg = format_error(ErrorCode.AUTH_FAILED, "Invalid credentials")

        assert "Invalid credentials" in error_msg
        assert "Details:" in error_msg

    def test_get_error_hint(self):
        """Test getting error hint"""
        from error_messages import ErrorCode, get_error_hint

        hint = get_error_hint(ErrorCode.OPENAI_API_ERROR)

        assert hint
        assert "API key" in hint or "credits" in hint


# ============================================================================
# SPRINT 3 TESTS - Caching and Parallel Processing
# ============================================================================


class TestCachingSystem:
    """Tests for Sprint 3 caching system"""

    def test_cache_boss_identification(self):
        """Test caching boss identification results"""
        from database import VideoDatabase

        db = VideoDatabase(":memory:")

        # Cache a boss identification
        result = db.cache_boss("video123", "Bloodborne", "Father Gascoigne", source="thumbnail", expiry_days=30)
        assert result is True

        # Retrieve cached result
        cached = db.get_cached_boss("video123", "Bloodborne")
        assert cached is not None
        assert cached["boss_name"] == "Father Gascoigne"
        assert cached["source"] == "thumbnail"
        assert cached["accessed_count"] == 1

    def test_cache_access_count(self):
        """Test cache access count increments"""
        from database import VideoDatabase

        db = VideoDatabase(":memory:")

        # Cache a result
        db.cache_boss("video456", "Elden Ring", "Margit", source="frames", expiry_days=30)

        # Access multiple times
        for _ in range(3):
            cached = db.get_cached_boss("video456", "Elden Ring")

        # Check access count
        cached = db.get_cached_boss("video456", "Elden Ring")
        assert cached["accessed_count"] == 4  # 3 previous + 1 current

    def test_cache_expiry(self):
        """Test cache expiry functionality"""

        from database import VideoDatabase

        db = VideoDatabase(":memory:")

        # Cache with 0 days expiry (immediate expiry)
        db.cache_boss("video789", "Dark Souls", "Ornstein", source="frames", expiry_days=0)

        # Should not retrieve expired cache
        cached = db.get_cached_boss("video789", "Dark Souls")
        assert cached is None

    def test_clear_cache(self):
        """Test clearing all cache"""
        from database import VideoDatabase

        db = VideoDatabase(":memory:")

        # Add multiple cache entries
        db.cache_boss("v1", "Game1", "Boss1", expiry_days=30)
        db.cache_boss("v2", "Game2", "Boss2", expiry_days=30)
        db.cache_boss("v3", "Game3", "Boss3", expiry_days=0)  # Expired

        # Clear cache
        total, expired = db.clear_cache()

        assert total == 3
        assert expired == 1

        # Verify cache is empty
        stats = db.get_cache_statistics()
        assert stats["total"] == 0

    def test_cleanup_expired_cache(self):
        """Test cleanup of expired cache entries"""
        from database import VideoDatabase

        db = VideoDatabase(":memory:")

        # Add both valid and expired entries
        db.cache_boss("v1", "Game1", "Boss1", expiry_days=30)
        db.cache_boss("v2", "Game2", "Boss2", expiry_days=0)  # Expired

        # Cleanup expired
        cleaned = db.cleanup_expired_cache()

        assert cleaned == 1

        # Verify valid entry still exists
        cached = db.get_cached_boss("v1", "Game1")
        assert cached is not None

    def test_cache_statistics(self):
        """Test cache statistics reporting"""
        from database import VideoDatabase

        db = VideoDatabase(":memory:")

        # Add entries
        db.cache_boss("v1", "Game1", "Boss1", expiry_days=30)
        db.cache_boss("v2", "Game2", "Boss2", expiry_days=0)  # Expired

        # Access one multiple times
        for _ in range(5):
            db.get_cached_boss("v1", "Game1")

        stats = db.get_cache_statistics()

        assert stats["total"] == 2
        assert stats["active"] == 1
        assert stats["expired"] == 1
        # cache_boss sets accessed_count to 1, then 5 get_cached_boss calls add 5 more = 6 total
        assert stats["max_accessed"] == 6

    def test_cache_integration_with_identify_boss(self, mock_config):
        """Test cache integration with boss identification"""
        with patch("youtube_boss_titles.openai.OpenAI"), patch("youtube_boss_titles.VideoDatabase") as mock_db_class:
            import logging

            mock_logger = logging.getLogger("test_logger")

            # Setup mock database
            mock_db = mock_db_class.return_value
            mock_db.get_cached_boss.return_value = {"boss_name": "Cached Boss", "source": "thumbnail"}

            updater = YouTubeBossUpdater(config=mock_config, logger_instance=mock_logger, db_path=":memory:")

            # Call identify_boss - should hit cache
            with patch.object(updater, "identify_boss_from_images"):
                boss_name = updater.identify_boss("video123", "TestGame")

            # Verify cache was checked
            mock_db.get_cached_boss.assert_called_once()
            assert boss_name == "Cached Boss"


class TestParallelProcessing:
    """Tests for Sprint 3 parallel processing"""

    def test_parallel_processing_enabled_via_config(self, mock_config):
        """Test parallel processing can be enabled via config"""
        mock_config.config["processing"]["parallel"]["enabled"] = True
        mock_config.config["processing"]["parallel"]["workers"] = 3

        assert mock_config.get("processing.parallel.enabled") is True
        assert mock_config.get("processing.parallel.workers") == 3

    def test_parallel_processing_disabled_by_default(self, mock_config):
        """Test parallel processing is disabled by default"""
        assert mock_config.get("processing.parallel.enabled") is False

    def test_workers_parameter_in_run(self, mock_config):
        """Test workers parameter is accepted in run method"""
        with patch("youtube_boss_titles.openai.OpenAI"), patch("youtube_boss_titles.VideoDatabase"):
            import logging

            mock_logger = logging.getLogger("test_logger")
            updater = YouTubeBossUpdater(config=mock_config, logger_instance=mock_logger, db_path=":memory:")

            # Mock authentication and sheets
            updater.youtube = Mock()
            updater.sheets_client = Mock()

            # Mock get_my_videos to return empty list
            with patch.object(updater, "get_my_videos", return_value=[]):  # noqa: SIM117
                with patch.object(updater, "authenticate_youtube"):
                    # Should not raise error with workers parameter
                    updater.run(dry_run=True, workers=3)

    def test_process_video_list_respects_workers_param(self, updater):
        """Test _process_video_list respects workers parameter"""
        videos = [{"id": "v1", "title": "Test_20250101000000", "published_at": "2025-01-01T00:00:00Z"}]

        # Mock the parallel processing method
        with patch.object(updater, "_process_video_list_parallel") as mock_parallel:
            updater._process_video_list(videos, dry_run=False, force=False, workers=5)

            # Should call parallel processing with 5 workers
            mock_parallel.assert_called_once_with(videos, False, 5)


class TestConfigurationUpdates:
    """Tests for Sprint 3 configuration updates"""

    def test_cache_config_defaults(self):
        """Test cache configuration has proper defaults"""
        config = Config()

        assert config.get("processing.cache.enabled") is True
        assert config.get("processing.cache.expiry_days") == 30

    def test_parallel_config_defaults(self):
        """Test parallel processing configuration has proper defaults"""
        config = Config()

        assert config.get("processing.parallel.enabled") is False
        assert config.get("processing.parallel.workers") == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--cov=youtube_boss_titles", "--cov-report=html"])
