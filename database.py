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

            # Create cache table for OpenAI responses
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS boss_cache (
                    cache_key TEXT PRIMARY KEY,
                    video_id TEXT,
                    game_name TEXT,
                    boss_name TEXT,
                    source TEXT,  -- 'thumbnail' or 'frames'
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP,
                    accessed_count INTEGER DEFAULT 0,
                    last_accessed TIMESTAMP
                )
            ''')

            # Create index on video_id for cache lookup
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_cache_video_id ON boss_cache(video_id)
            ''')

            # Create index on expires_at for cleanup
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_cache_expires ON boss_cache(expires_at)
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

    # Cache-related methods

    def _generate_cache_key(self, video_id: str, game_name: str) -> str:
        """Generate cache key for boss identification"""
        import hashlib
        key = f"{video_id}:{game_name}"
        return hashlib.sha256(key.encode()).hexdigest()

    def get_cached_boss(self, video_id: str, game_name: str) -> Optional[Dict]:
        """Get cached boss identification result"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cache_key = self._generate_cache_key(video_id, game_name)

                # Get cache entry
                cursor.execute('''
                    SELECT * FROM boss_cache
                    WHERE cache_key = ? AND (expires_at IS NULL OR expires_at > ?)
                ''', (cache_key, datetime.now().isoformat()))

                row = cursor.fetchone()
                if not row:
                    return None

                # Update access count and timestamp
                cursor.execute('''
                    UPDATE boss_cache
                    SET accessed_count = accessed_count + 1,
                        last_accessed = ?
                    WHERE cache_key = ?
                ''', (datetime.now().isoformat(), cache_key))
                conn.commit()

                return dict(row)
        except sqlite3.Error as e:
            print(f"Database error getting cached boss for {video_id}: {e}")
            return None

    def cache_boss(self, video_id: str, game_name: str, boss_name: str,
                   source: str = 'frames', expiry_days: int = 30) -> bool:
        """Cache boss identification result"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cache_key = self._generate_cache_key(video_id, game_name)

                # Calculate expiry date
                from datetime import timedelta
                expires_at = (datetime.now() + timedelta(days=expiry_days)).isoformat()

                cursor.execute('''
                    INSERT OR REPLACE INTO boss_cache
                    (cache_key, video_id, game_name, boss_name, source, expires_at, last_accessed, accessed_count)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                ''', (cache_key, video_id, game_name, boss_name, source, expires_at,
                      datetime.now().isoformat()))
                conn.commit()
                return True
        except sqlite3.Error as e:
            print(f"Database error caching boss for {video_id}: {e}")
            return False

    def clear_cache(self) -> Tuple[int, int]:
        """
        Clear all cache entries
        Returns: (total_cleared, expired_cleared)
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # Count expired entries
                cursor.execute('''
                    SELECT COUNT(*) as count FROM boss_cache
                    WHERE expires_at IS NOT NULL AND expires_at <= ?
                ''', (datetime.now().isoformat(),))
                expired_count = cursor.fetchone()['count']

                # Count total entries
                cursor.execute('SELECT COUNT(*) as count FROM boss_cache')
                total_count = cursor.fetchone()['count']

                # Clear all cache
                cursor.execute('DELETE FROM boss_cache')
                conn.commit()

                return (total_count, expired_count)
        except sqlite3.Error as e:
            print(f"Database error clearing cache: {e}")
            return (0, 0)

    def cleanup_expired_cache(self) -> int:
        """Remove expired cache entries"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    DELETE FROM boss_cache
                    WHERE expires_at IS NOT NULL AND expires_at <= ?
                ''', (datetime.now().isoformat(),))
                count = cursor.rowcount
                conn.commit()
                return count
        except sqlite3.Error as e:
            print(f"Database error cleaning up expired cache: {e}")
            return 0

    def get_cache_statistics(self) -> Dict[str, int]:
        """Get cache statistics"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # Total entries
                cursor.execute('SELECT COUNT(*) as count FROM boss_cache')
                total = cursor.fetchone()['count']

                # Expired entries
                cursor.execute('''
                    SELECT COUNT(*) as count FROM boss_cache
                    WHERE expires_at IS NOT NULL AND expires_at <= ?
                ''', (datetime.now().isoformat(),))
                expired = cursor.fetchone()['count']

                # Active entries
                active = total - expired

                # Most accessed
                cursor.execute('''
                    SELECT MAX(accessed_count) as max_accessed FROM boss_cache
                ''')
                max_accessed = cursor.fetchone()['max_accessed'] or 0

                return {
                    'total': total,
                    'active': active,
                    'expired': expired,
                    'max_accessed': max_accessed
                }
        except sqlite3.Error as e:
            print(f"Database error getting cache statistics: {e}")
            return {}


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
