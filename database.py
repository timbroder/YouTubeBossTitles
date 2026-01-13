#!/usr/bin/env python3
"""
Database operations for YouTube Boss Title Updater
Tracks processed videos, their state, and errors
"""

import sqlite3
from datetime import datetime
from typing import Optional, List, Dict, Tuple
from contextlib import contextmanager
from pathlib import Path


class VideoDatabase:
    """SQLite database for tracking processed videos"""

    def __init__(self, db_path: str = 'processed_videos.db'):
        """Initialize database connection"""
        self.db_path = db_path
        self._initialize_database()

    def _initialize_database(self):
        """Create database tables if they don't exist"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Create processed_videos table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS processed_videos (
                    video_id TEXT PRIMARY KEY,
                    original_title TEXT,
                    new_title TEXT,
                    game_name TEXT,
                    boss_name TEXT,
                    status TEXT NOT NULL CHECK(status IN ('pending', 'processing', 'completed', 'failed')),
                    attempts INTEGER DEFAULT 0,
                    last_attempt TIMESTAMP,
                    error_message TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Create index on status for faster queries
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_status ON processed_videos(status)
            ''')

            # Create index on game_name for filtering
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_game_name ON processed_videos(game_name)
            ''')

            conn.commit()

    @contextmanager
    def get_connection(self):
        """Context manager for database connections"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # Enable column access by name
        try:
            yield conn
        finally:
            conn.close()

    def add_video(self, video_id: str, original_title: str, game_name: str,
                  status: str = 'pending') -> bool:
        """Add a new video to track"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR IGNORE INTO processed_videos
                    (video_id, original_title, game_name, status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (video_id, original_title, game_name, status,
                      datetime.now().isoformat(), datetime.now().isoformat()))
                conn.commit()
                return cursor.rowcount > 0
        except sqlite3.Error as e:
            print(f"Database error adding video {video_id}: {e}")
            return False

    def get_video(self, video_id: str) -> Optional[Dict]:
        """Get video record by ID"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM processed_videos WHERE video_id = ?', (video_id,))
                row = cursor.fetchone()
                return dict(row) if row else None
        except sqlite3.Error as e:
            print(f"Database error getting video {video_id}: {e}")
            return None

    def update_video_status(self, video_id: str, status: str,
                           new_title: Optional[str] = None,
                           boss_name: Optional[str] = None,
                           error_message: Optional[str] = None) -> bool:
        """Update video status and related fields"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # Build update query dynamically
                updates = ['status = ?', 'updated_at = ?']
                params = [status, datetime.now().isoformat()]

                if new_title is not None:
                    updates.append('new_title = ?')
                    params.append(new_title)

                if boss_name is not None:
                    updates.append('boss_name = ?')
                    params.append(boss_name)

                if error_message is not None:
                    updates.append('error_message = ?')
                    params.append(error_message)

                # Update last_attempt timestamp
                updates.append('last_attempt = ?')
                params.append(datetime.now().isoformat())

                # Increment attempts counter
                updates.append('attempts = attempts + 1')

                params.append(video_id)

                query = f'''
                    UPDATE processed_videos
                    SET {', '.join(updates)}
                    WHERE video_id = ?
                '''

                cursor.execute(query, params)
                conn.commit()
                return cursor.rowcount > 0
        except sqlite3.Error as e:
            print(f"Database error updating video {video_id}: {e}")
            return False

    def get_videos_by_status(self, status: str) -> List[Dict]:
        """Get all videos with a specific status"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM processed_videos WHERE status = ?', (status,))
                return [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            print(f"Database error getting videos by status {status}: {e}")
            return []

    def get_failed_videos(self, max_attempts: int = 3) -> List[Dict]:
        """Get videos that have failed but haven't exceeded max attempts"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT * FROM processed_videos
                    WHERE status = 'failed' AND attempts < ?
                    ORDER BY last_attempt ASC
                ''', (max_attempts,))
                return [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            print(f"Database error getting failed videos: {e}")
            return []

    def get_pending_videos(self) -> List[Dict]:
        """Get all pending videos"""
        return self.get_videos_by_status('pending')

    def is_processed(self, video_id: str) -> bool:
        """Check if video has been successfully processed"""
        video = self.get_video(video_id)
        return video is not None and video['status'] == 'completed'

    def get_statistics(self) -> Dict[str, int]:
        """Get processing statistics"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT
                        status,
                        COUNT(*) as count
                    FROM processed_videos
                    GROUP BY status
                ''')
                stats = {row['status']: row['count'] for row in cursor.fetchall()}

                # Get total count
                cursor.execute('SELECT COUNT(*) as total FROM processed_videos')
                stats['total'] = cursor.fetchone()['total']

                return stats
        except sqlite3.Error as e:
            print(f"Database error getting statistics: {e}")
            return {}

    def clear_processing_status(self):
        """
        Reset any 'processing' status to 'pending'
        Useful for recovery after crashes
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE processed_videos
                    SET status = 'pending', updated_at = ?
                    WHERE status = 'processing'
                ''', (datetime.now().isoformat(),))
                count = cursor.rowcount
                conn.commit()
                if count > 0:
                    print(f"Reset {count} videos from 'processing' to 'pending' status")
        except sqlite3.Error as e:
            print(f"Database error clearing processing status: {e}")

    def get_games_summary(self) -> List[Tuple[str, int, int]]:
        """Get summary of games with completed and total counts"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT
                        game_name,
                        COUNT(*) as total,
                        SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed
                    FROM processed_videos
                    GROUP BY game_name
                    ORDER BY total DESC
                ''')
                return [(row['game_name'], row['total'], row['completed'])
                        for row in cursor.fetchall()]
        except sqlite3.Error as e:
            print(f"Database error getting games summary: {e}")
            return []

    def delete_video(self, video_id: str) -> bool:
        """Delete a video record (for rollback scenarios)"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM processed_videos WHERE video_id = ?', (video_id,))
                conn.commit()
                return cursor.rowcount > 0
        except sqlite3.Error as e:
            print(f"Database error deleting video {video_id}: {e}")
            return False


def exponential_backoff(attempt: int, base_delay: float = 2.0, max_delay: float = 60.0) -> float:
    """
    Calculate exponential backoff delay

    Args:
        attempt: Current attempt number (0-indexed)
        base_delay: Base delay in seconds
        max_delay: Maximum delay in seconds

    Returns:
        Delay in seconds
    """
    delay = base_delay * (2 ** attempt)
    return min(delay, max_delay)
