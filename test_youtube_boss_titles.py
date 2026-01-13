"""
Unit and Integration Tests for YouTube Boss Title Updater
"""

import pytest
import os
import json
from unittest.mock import Mock, MagicMock, patch, call
from datetime import datetime

from youtube_boss_titles import YouTubeBossUpdater, SOULSLIKE_GAMES
from config import Config


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def mock_config():
    """Provide a mock Config object"""
    config = Config()
    # Override API key for testing
    config.config['openai']['api_key'] = 'test-openai-key-12345'
    return config


@pytest.fixture
def updater(mock_config):
    """Create a YouTubeBossUpdater instance with mocked OpenAI client"""
    with patch('youtube_boss_titles.openai.OpenAI'):
        with patch('youtube_boss_titles.VideoDatabase'):
            return YouTubeBossUpdater(config=mock_config, db_path=':memory:')


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
        {
            'id': 'video1',
            'title': 'Bloodborne_20250321184741',
            'published_at': '2025-03-21T18:47:41Z'
        },
        {
            'id': 'video2',
            'title': 'Clair Obscur: Expedition 33_20250629134801',
            'published_at': '2025-06-29T13:48:01Z'
        },
        {
            'id': 'video3',
            'title': 'Regular Video Title',
            'published_at': '2025-01-01T00:00:00Z'
        }
    ]


# ============================================================================
# UNIT TESTS - Title Detection and Parsing
# ============================================================================

class TestTitleDetection:
    """Test PS5 title detection and parsing"""

    def test_is_default_ps5_title_valid(self, updater):
        """Test detection of valid PS5 default titles"""
        assert updater.is_default_ps5_title('Bloodborne_20250321184741') is True
        assert updater.is_default_ps5_title('Game Name_20250101000000') is True
        assert updater.is_default_ps5_title('Clair Obscur: Expedition 33_20250629134801') is True

    def test_is_default_ps5_title_invalid(self, updater):
        """Test rejection of non-PS5 titles"""
        assert updater.is_default_ps5_title('Regular Video Title') is False
        assert updater.is_default_ps5_title('Game_123') is False
        assert updater.is_default_ps5_title('') is False
        assert updater.is_default_ps5_title('NoUnderscore20250321184741') is False

    def test_extract_game_name(self, updater):
        """Test game name extraction from PS5 titles"""
        assert updater.extract_game_name('Bloodborne_20250321184741') == 'Bloodborne'
        assert updater.extract_game_name('Dark Souls III_20250101000000') == 'Dark Souls III'
        assert updater.extract_game_name('Clair Obscur: Expedition 33_20250629134801') == 'Clair Obscur: Expedition 33'

    def test_is_soulslike(self, updater):
        """Test souls-like game detection"""
        assert updater.is_soulslike('Bloodborne') is True
        assert updater.is_soulslike('Dark Souls III') is True
        assert updater.is_soulslike('Elden Ring') is True
        assert updater.is_soulslike('Sekiro: Shadows Die Twice') is True
        assert updater.is_soulslike('Clair Obscur: Expedition 33') is False
        assert updater.is_soulslike('God of War') is False


# ============================================================================
# UNIT TESTS - Title Formatting
# ============================================================================

class TestTitleFormatting:
    """Test video title formatting"""

    def test_format_title_regular_game(self, updater):
        """Test title formatting for regular games"""
        result = updater.format_title('Clair Obscur: Expedition 33', 'Final Boss')
        assert result == 'Clair Obscur: Expedition 33: Final Boss PS5'

    def test_format_title_soulslike_game(self, updater):
        """Test title formatting for souls-like games"""
        result = updater.format_title('Bloodborne', 'Father Gascoigne')
        assert result == 'Bloodborne: Father Gascoigne Melee PS5'

        result = updater.format_title('Elden Ring', 'Malenia')
        assert result == 'Elden Ring: Malenia Melee PS5'


# ============================================================================
# UNIT TESTS - Authentication
# ============================================================================

class TestAuthentication:
    """Test authentication flows"""

    @patch('youtube_boss_titles.os.path.exists')
    @patch('youtube_boss_titles.Credentials.from_authorized_user_file')
    @patch('youtube_boss_titles.build')
    @patch('youtube_boss_titles.gspread.authorize')
    def test_authenticate_with_existing_token(self, mock_gspread, mock_build,
                                             mock_creds_from_file, mock_exists,
                                             updater, mock_credentials):
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

    @patch('youtube_boss_titles.os.path.exists')
    @patch('youtube_boss_titles.InstalledAppFlow.from_client_secrets_file')
    @patch('youtube_boss_titles.build')
    @patch('youtube_boss_titles.gspread.authorize')
    @patch('builtins.open', create=True)
    def test_authenticate_without_token(self, mock_open, mock_gspread, mock_build,
                                       mock_flow, mock_exists, updater, mock_credentials):
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
        url = updater.get_video_thumbnail_url('test_video_id')
        assert url == 'https://img.youtube.com/vi/test_video_id/maxresdefault.jpg'

    @patch('youtube_boss_titles.tempfile.mkdtemp')
    @patch('youtube_boss_titles.yt_dlp.YoutubeDL')
    @patch('youtube_boss_titles.subprocess.run')
    @patch('youtube_boss_titles.os.path.exists')
    @patch('builtins.open', create=True)
    @patch('youtube_boss_titles.base64.b64encode')
    def test_extract_video_frames_success(self, mock_b64, mock_open, mock_exists,
                                         mock_subprocess, mock_ytdl, mock_mkdtemp, updater):
        """Test successful video frame extraction"""
        mock_mkdtemp.return_value = '/tmp/test'
        mock_exists.side_effect = [True, True, True]  # video exists, frames exist
        mock_b64.return_value.decode.return_value = 'base64encodedimage'

        mock_ytdl_instance = Mock()
        mock_ytdl.return_value.__enter__.return_value = mock_ytdl_instance
        mock_subprocess.return_value = Mock()

        frames = updater.extract_video_frames('test_video_id', timestamps=[10, 20])

        assert len(frames) == 2
        assert all(frame.startswith('data:image/jpeg;base64,') for frame in frames)

    def test_get_my_videos(self, updater, sample_ps5_videos):
        """Test fetching videos from channel"""
        mock_youtube = Mock()

        # Mock channels().list() response
        mock_channels_response = {
            'items': [{
                'contentDetails': {
                    'relatedPlaylists': {'uploads': 'UU_playlist_id'}
                }
            }]
        }

        # Mock playlistItems().list() response
        mock_playlist_response = {
            'items': [
                {
                    'snippet': {
                        'resourceId': {'videoId': v['id']},
                        'title': v['title'],
                        'publishedAt': v['published_at']
                    }
                } for v in sample_ps5_videos
            ]
        }

        mock_youtube.channels().list().execute.return_value = mock_channels_response
        mock_youtube.playlistItems().list().execute.return_value = mock_playlist_response

        updater.youtube = mock_youtube

        videos = updater.get_my_videos()

        assert len(videos) == 3
        assert videos[0]['title'] == 'Bloodborne_20250321184741'


# ============================================================================
# UNIT TESTS - Boss Identification
# ============================================================================

class TestBossIdentification:
    """Test boss identification logic"""

    def test_identify_boss_from_images_success(self, updater):
        """Test successful boss identification from images"""
        mock_response = Mock()
        mock_response.choices = [Mock(message=Mock(content='Father Gascoigne'))]

        updater.openai_client.chat.completions.create = Mock(return_value=mock_response)

        boss_name = updater.identify_boss_from_images(
            ['http://example.com/image.jpg'],
            'Bloodborne'
        )

        assert boss_name == 'Father Gascoigne'
        updater.openai_client.chat.completions.create.assert_called_once()

    def test_identify_boss_from_images_unknown(self, updater):
        """Test boss identification when boss is unknown"""
        mock_response = Mock()
        mock_response.choices = [Mock(message=Mock(content='Unknown Boss'))]

        updater.openai_client.chat.completions.create = Mock(return_value=mock_response)

        boss_name = updater.identify_boss_from_images(
            ['http://example.com/image.jpg'],
            'Some Game'
        )

        assert boss_name is None

    def test_identify_boss_from_images_api_error(self, updater):
        """Test boss identification when API fails"""
        updater.openai_client.chat.completions.create = Mock(
            side_effect=Exception('API Error')
        )

        boss_name = updater.identify_boss_from_images(
            ['http://example.com/image.jpg'],
            'Bloodborne'
        )

        assert boss_name is None

    def test_identify_boss_thumbnail_success(self, updater):
        """Test boss identification using thumbnail (hybrid approach - first attempt)"""
        mock_response = Mock()
        mock_response.choices = [Mock(message=Mock(content='Cleric Beast'))]

        updater.openai_client.chat.completions.create = Mock(return_value=mock_response)
        updater.get_video_thumbnail_url = Mock(return_value='http://thumbnail.jpg')

        boss_name = updater.identify_boss('video123', 'Bloodborne')

        assert boss_name == 'Cleric Beast'

    def test_identify_boss_fallback_to_frames(self, updater):
        """Test boss identification falling back to frame extraction"""
        # First call (thumbnail) returns None, second call (frames) succeeds
        mock_response_fail = Mock()
        mock_response_fail.choices = [Mock(message=Mock(content='Unknown Boss'))]

        mock_response_success = Mock()
        mock_response_success.choices = [Mock(message=Mock(content='Blood-starved Beast'))]

        updater.openai_client.chat.completions.create = Mock(
            side_effect=[mock_response_fail, mock_response_success]
        )
        updater.get_video_thumbnail_url = Mock(return_value='http://thumbnail.jpg')
        updater.extract_video_frames = Mock(return_value=['frame1', 'frame2'])

        boss_name = updater.identify_boss('video123', 'Bloodborne')

        assert boss_name == 'Blood-starved Beast'
        assert updater.openai_client.chat.completions.create.call_count == 2


# ============================================================================
# UNIT TESTS - Playlist Management
# ============================================================================

class TestPlaylistManagement:
    """Test playlist operations"""

    def test_get_or_create_playlist_existing(self, updater):
        """Test getting an existing playlist"""
        mock_youtube = Mock()
        mock_playlists_response = {
            'items': [
                {'id': 'playlist123', 'snippet': {'title': 'Bloodborne'}}
            ]
        }

        mock_youtube.playlists().list().execute.return_value = mock_playlists_response
        updater.youtube = mock_youtube

        playlist_id = updater.get_or_create_playlist('Bloodborne')

        assert playlist_id == 'playlist123'

    def test_get_or_create_playlist_new(self, updater):
        """Test creating a new playlist"""
        mock_youtube = Mock()

        # No existing playlists
        mock_playlists_response = {'items': []}
        mock_youtube.playlists().list().execute.return_value = mock_playlists_response

        # Create new playlist
        mock_create_response = {'id': 'new_playlist456'}
        mock_youtube.playlists().insert().execute.return_value = mock_create_response

        updater.youtube = mock_youtube

        playlist_id = updater.get_or_create_playlist('Elden Ring')

        assert playlist_id == 'new_playlist456'

    def test_add_video_to_playlist_success(self, updater):
        """Test adding video to playlist"""
        mock_youtube = Mock()
        mock_youtube.playlistItems().insert().execute.return_value = {}
        updater.youtube = mock_youtube

        result = updater.add_video_to_playlist('video123', 'playlist456')

        assert result is True

    def test_add_video_to_playlist_already_exists(self, updater):
        """Test adding video that's already in playlist"""
        mock_youtube = Mock()
        mock_youtube.playlistItems().insert().execute.side_effect = Exception('videoAlreadyInPlaylist')
        updater.youtube = mock_youtube

        result = updater.add_video_to_playlist('video123', 'playlist456')

        assert result is True  # Should still return True


# ============================================================================
# UNIT TESTS - Google Sheets Logging
# ============================================================================

class TestSheetsLogging:
    """Test Google Sheets logging"""

    @patch('youtube_boss_titles.gspread')
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
        class MockSpreadsheetNotFound(Exception):
            pass

        mock_spreadsheet = Mock()
        mock_sheet = Mock()
        mock_spreadsheet.sheet1 = mock_sheet
        mock_spreadsheet.url = 'https://docs.google.com/spreadsheets/test'

        mock_sheets_client = Mock()
        mock_sheets_client.open.side_effect = MockSpreadsheetNotFound
        mock_sheets_client.create.return_value = mock_spreadsheet
        updater.sheets_client = mock_sheets_client

        # Patch the exception in the actual code
        with patch('youtube_boss_titles.gspread.exceptions.SpreadsheetNotFound', MockSpreadsheetNotFound):
            updater.setup_log_spreadsheet()

        assert updater.log_sheet == mock_sheet
        mock_sheet.append_row.assert_called_once()
        mock_sheet.format.assert_called_once()

    def test_log_video_update(self, updater):
        """Test logging video update to spreadsheet"""
        mock_sheet = Mock()
        updater.log_sheet = mock_sheet

        updater.log_video_update(
            video_id='video123',
            original_title='Bloodborne_20250321184741',
            new_title='Bloodborne: Father Gascoigne Melee PS5',
            playlist_name='Bloodborne',
            playlist_id='playlist456'
        )

        mock_sheet.append_row.assert_called_once()
        call_args = mock_sheet.append_row.call_args[0][0]

        assert 'Bloodborne_20250321184741' in call_args
        assert 'Bloodborne: Father Gascoigne Melee PS5' in call_args
        assert 'https://www.youtube.com/watch?v=video123' in call_args
        assert 'https://www.youtube.com/playlist?list=playlist456' in call_args


# ============================================================================
# UNIT TESTS - Video Title Updates
# ============================================================================

class TestVideoTitleUpdate:
    """Test video title update operations"""

    def test_update_video_title_success(self, updater):
        """Test successful video title update"""
        mock_youtube = Mock()
        mock_video_response = {
            'items': [{
                'id': 'video123',
                'snippet': {'title': 'Old Title'}
            }]
        }

        mock_youtube.videos().list().execute.return_value = mock_video_response
        mock_youtube.videos().update().execute.return_value = {}
        updater.youtube = mock_youtube

        result = updater.update_video_title('video123', 'New Title')

        assert result is True

    def test_update_video_title_not_found(self, updater):
        """Test updating video that doesn't exist"""
        mock_youtube = Mock()
        mock_youtube.videos().list().execute.return_value = {'items': []}
        updater.youtube = mock_youtube

        result = updater.update_video_title('nonexistent', 'New Title')

        assert result is False


# ============================================================================
# INTEGRATION TESTS
# ============================================================================

class TestIntegration:
    """Integration tests for full workflows"""

    @patch('youtube_boss_titles.openai.OpenAI')
    @patch('youtube_boss_titles.VideoDatabase')
    def test_process_video_full_workflow(self, mock_db, mock_openai_class, mock_config):
        """Test full video processing workflow"""
        # Setup
        updater = YouTubeBossUpdater(config=mock_config, db_path=':memory:')

        # Mock YouTube API
        mock_youtube = Mock()
        mock_video_response = {
            'items': [{
                'id': 'video123',
                'snippet': {'title': 'Bloodborne_20250321184741'}
            }]
        }
        mock_youtube.videos().list().execute.return_value = mock_video_response
        mock_youtube.videos().update().execute.return_value = {}

        # Mock playlist operations
        mock_playlists_response = {'items': []}
        mock_youtube.playlists().list().execute.return_value = mock_playlists_response
        mock_youtube.playlists().insert().execute.return_value = {'id': 'new_playlist'}
        mock_youtube.playlistItems().insert().execute.return_value = {}

        updater.youtube = mock_youtube

        # Mock OpenAI response
        mock_openai_instance = Mock()
        mock_response = Mock()
        mock_response.choices = [Mock(message=Mock(content='Father Gascoigne'))]
        mock_openai_instance.chat.completions.create.return_value = mock_response
        updater.openai_client = mock_openai_instance

        # Mock sheets logging
        mock_sheet = Mock()
        updater.log_sheet = mock_sheet

        # Execute
        video = {
            'id': 'video123',
            'title': 'Bloodborne_20250321184741',
            'published_at': '2025-03-21T18:47:41Z'
        }

        result = updater.process_video(video)

        # Verify
        assert result is True
        mock_youtube.videos().update().execute.assert_called_once()
        mock_youtube.playlists().insert().execute.assert_called_once()
        mock_sheet.append_row.assert_called_once()

    def test_process_video_skip_non_ps5_title(self, updater):
        """Test that non-PS5 titles are skipped"""
        video = {
            'id': 'video123',
            'title': 'Regular Video Title',
            'published_at': '2025-01-01T00:00:00Z'
        }

        result = updater.process_video(video)

        assert result is False

    @patch('youtube_boss_titles.openai.OpenAI')
    @patch('youtube_boss_titles.VideoDatabase')
    def test_process_video_skip_when_boss_not_identified(self, mock_db, mock_openai_class, mock_config):
        """Test that videos are skipped when boss can't be identified"""
        updater = YouTubeBossUpdater(config=mock_config, db_path=':memory:')

        # Mock OpenAI to return Unknown Boss
        mock_openai_instance = Mock()
        mock_response = Mock()
        mock_response.choices = [Mock(message=Mock(content='Unknown Boss'))]
        mock_openai_instance.chat.completions.create.return_value = mock_response
        updater.openai_client = mock_openai_instance

        # Mock frame extraction to return empty
        updater.extract_video_frames = Mock(return_value=[])

        video = {
            'id': 'video123',
            'title': 'Bloodborne_20250321184741',
            'published_at': '2025-03-21T18:47:41Z'
        }

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
        result = updater.extract_game_name('_20250321184741')
        assert result == ''

    def test_format_title_with_special_characters(self, updater):
        """Test title formatting with special characters"""
        result = updater.format_title('Game: Special Edition', 'Boss & Enemy')
        assert result == 'Game: Special Edition: Boss & Enemy PS5'

    def test_log_video_update_without_initialized_sheet(self, updater):
        """Test logging when sheet is not initialized"""
        updater.log_sheet = None

        # Should not raise exception
        updater.log_video_update(
            video_id='video123',
            original_title='Old Title',
            new_title='New Title',
            playlist_name='Game',
            playlist_id='playlist123'
        )

    def test_identify_boss_with_empty_frames(self, updater):
        """Test boss identification when frame extraction returns empty list"""
        mock_response = Mock()
        mock_response.choices = [Mock(message=Mock(content='Unknown Boss'))]
        updater.openai_client.chat.completions.create = Mock(return_value=mock_response)

        updater.extract_video_frames = Mock(return_value=[])

        result = updater.identify_boss('video123', 'Bloodborne')

        assert result is None


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--cov=youtube_boss_titles', '--cov-report=html'])
