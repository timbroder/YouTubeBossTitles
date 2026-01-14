#!/usr/bin/env python3
"""
Rollback system for YouTube Boss Title Updater
Allows reverting video title changes
"""

import logging
from datetime import datetime
from typing import Optional

from rich.console import Console
from rich.prompt import Confirm
from rich.table import Table

console = Console()


class RollbackManager:
    """
    Manages rollback operations for video title updates

    Allows reverting changes to original titles with confirmation prompts
    and audit logging
    """

    def __init__(self, updater, logger: Optional[logging.Logger] = None):
        """
        Initialize rollback manager

        Args:
            updater: YouTubeBossUpdater instance
            logger: Optional logger instance

        Example:
            >>> from config import Config
            >>> from youtube_boss_titles import YouTubeBossUpdater
            >>> config = Config()
            >>> updater = YouTubeBossUpdater(config)
            >>> rollback = RollbackManager(updater)
        """
        self.updater = updater
        self.logger = logger or logging.getLogger(__name__)
        self.youtube = updater.youtube
        self.db = updater.db
        self.sheets_client = updater.sheets_client
        self.log_sheet = updater.log_sheet

    def rollback_video(self, video_id: str, confirm: bool = True, update_sheets: bool = True) -> bool:
        """
        Rollback a single video to its original title

        Args:
            video_id: YouTube video ID to rollback
            confirm: Whether to prompt for confirmation (default: True)
            update_sheets: Whether to log rollback in Google Sheets (default: True)

        Returns:
            True if rollback successful, False otherwise

        Example:
            >>> rollback = RollbackManager(updater)
            >>> success = rollback.rollback_video("abc123")
        """
        # Get video record from database
        video = self.db.get_video(video_id)

        if not video:
            console.print(f"[red]✗[/red] Video {video_id} not found in database")
            self.logger.error(f"Rollback failed: Video {video_id} not in database")
            return False

        original_title = video.get("original_title")
        new_title = video.get("new_title")

        if not original_title:
            console.print(f"[yellow]⚠[/yellow] No original title stored for video {video_id}")
            self.logger.warning(f"Rollback skipped: No original title for {video_id}")
            return False

        if not new_title:
            console.print(f"[yellow]⚠[/yellow] Video {video_id} was never updated")
            self.logger.warning(f"Rollback skipped: Video {video_id} was never updated")
            return False

        # Display change information
        console.print(f"\n[bold]Rollback Video: {video_id}[/bold]")
        console.print(f"Current title: [cyan]{new_title}[/cyan]")
        console.print(f"Original title: [green]{original_title}[/green]")

        # Confirm rollback
        if confirm and not Confirm.ask("\nDo you want to rollback this video?"):
            console.print("[yellow]Rollback cancelled[/yellow]")
            return False

        # Update video title via YouTube API
        try:
            console.print(f"[dim]Rolling back video {video_id}...[/dim]")

            # Get current video snippet
            video_response = self.youtube.videos().list(part="snippet", id=video_id).execute()

            if not video_response.get("items"):
                console.print(f"[red]✗[/red] Video {video_id} not found on YouTube")
                self.logger.error(f"Rollback failed: Video {video_id} not found on YouTube")
                return False

            video_snippet = video_response["items"][0]["snippet"]

            # Update title
            video_snippet["title"] = original_title

            # Update via API
            self.youtube.videos().update(part="snippet", body={"id": video_id, "snippet": video_snippet}).execute()

            console.print(f"[green]✓[/green] Successfully rolled back video {video_id}")
            self.logger.info(f"Rolled back video {video_id} to original title: {original_title}")

            # Update database status
            self.db.update_video_status(
                video_id=video_id,
                status="completed",  # Keep as completed but with original title
                new_title=original_title,
                error_message=None,
            )

            # Log rollback in Google Sheets
            if update_sheets and self.log_sheet:
                try:
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    self.log_sheet.append_row(
                        [
                            timestamp,
                            video_id,
                            video.get("game_name", ""),
                            "",  # boss_name (empty for rollback)
                            original_title,
                            new_title,
                            "ROLLBACK",
                            "",
                        ]
                    )
                    self.logger.info(f"Logged rollback to Google Sheets for {video_id}")
                except Exception as e:
                    console.print(f"[yellow]⚠[/yellow] Failed to log rollback to Google Sheets: {e}")
                    self.logger.error(f"Failed to log rollback to sheets: {e}")

            return True

        except Exception as e:
            console.print(f"[red]✗[/red] Failed to rollback video {video_id}: {e}")
            self.logger.error(f"Rollback failed for {video_id}: {e}")
            return False

    def rollback_all(self, confirm: bool = True, update_sheets: bool = True) -> tuple[int, int]:
        """
        Rollback all videos that have been updated

        Args:
            confirm: Whether to prompt for confirmation (default: True)
            update_sheets: Whether to log rollbacks in Google Sheets (default: True)

        Returns:
            Tuple of (successful_count, failed_count)

        Example:
            >>> rollback = RollbackManager(updater)
            >>> success, failed = rollback.rollback_all()
            >>> print(f"Rolled back {success} videos, {failed} failed")
        """
        # Get all completed videos from database
        completed_videos = self.db.get_videos_by_status("completed")

        if not completed_videos:
            console.print("[yellow]No videos to rollback[/yellow]")
            return (0, 0)

        # Filter videos that have both original and new titles
        videos_to_rollback = [
            v
            for v in completed_videos
            if v.get("original_title") and v.get("new_title") and v["original_title"] != v["new_title"]
        ]

        if not videos_to_rollback:
            console.print("[yellow]No videos with changes to rollback[/yellow]")
            return (0, 0)

        # Display summary
        table = Table(title=f"Videos to Rollback ({len(videos_to_rollback)} total)")
        table.add_column("Video ID", style="cyan")
        table.add_column("Game", style="green")
        table.add_column("Current Title", style="yellow")
        table.add_column("Original Title", style="magenta")

        for video in videos_to_rollback[:10]:  # Show first 10
            table.add_row(
                video["video_id"],
                video.get("game_name", "Unknown"),
                (
                    video.get("new_title", "")[:50] + "..."
                    if len(video.get("new_title", "")) > 50
                    else video.get("new_title", "")
                ),
                (
                    video.get("original_title", "")[:50] + "..."
                    if len(video.get("original_title", "")) > 50
                    else video.get("original_title", "")
                ),
            )

        if len(videos_to_rollback) > 10:
            console.print(f"\n[dim]... and {len(videos_to_rollback) - 10} more videos[/dim]")

        console.print(table)

        # Confirm rollback
        if confirm:
            console.print(f"\n[bold red]WARNING:[/bold red] This will rollback {len(videos_to_rollback)} videos!")
            if not Confirm.ask("Are you sure you want to proceed?"):
                console.print("[yellow]Rollback cancelled[/yellow]")
                return (0, 0)

        # Perform rollback for each video
        success_count = 0
        failed_count = 0

        console.print(f"\n[bold]Rolling back {len(videos_to_rollback)} videos...[/bold]")

        for video in videos_to_rollback:
            video_id = video["video_id"]

            # Don't prompt for individual confirmations during batch rollback
            if self.rollback_video(video_id, confirm=False, update_sheets=update_sheets):
                success_count += 1
            else:
                failed_count += 1

        # Display summary
        console.print("\n[bold]Rollback Summary:[/bold]")
        console.print(f"  [green]✓[/green] Successfully rolled back: {success_count}")
        console.print(f"  [red]✗[/red] Failed: {failed_count}")

        self.logger.info(f"Batch rollback completed: {success_count} succeeded, {failed_count} failed")

        return (success_count, failed_count)

    def list_rollback_candidates(self) -> list[dict]:
        """
        List all videos that can be rolled back

        Returns:
            List of video records that have been updated and can be rolled back

        Example:
            >>> rollback = RollbackManager(updater)
            >>> candidates = rollback.list_rollback_candidates()
            >>> for video in candidates:
            ...     print(f"{video['video_id']}: {video['new_title']}")
        """
        completed_videos = self.db.get_videos_by_status("completed")

        # Filter videos that have both original and new titles
        candidates = [
            v
            for v in completed_videos
            if v.get("original_title") and v.get("new_title") and v["original_title"] != v["new_title"]
        ]

        return candidates

    def display_rollback_candidates(self) -> None:
        """
        Display a table of all videos that can be rolled back

        Example:
            >>> rollback = RollbackManager(updater)
            >>> rollback.display_rollback_candidates()
        """
        candidates = self.list_rollback_candidates()

        if not candidates:
            console.print("[yellow]No videos available for rollback[/yellow]")
            return

        table = Table(title=f"Rollback Candidates ({len(candidates)} total)")
        table.add_column("Video ID", style="cyan")
        table.add_column("Game", style="green")
        table.add_column("Boss", style="yellow")
        table.add_column("Current Title", style="magenta", max_width=40)
        table.add_column("Original Title", style="blue", max_width=40)
        table.add_column("Updated At", style="dim")

        for video in candidates:
            table.add_row(
                video["video_id"],
                video.get("game_name", "Unknown"),
                video.get("boss_name", "Unknown"),
                (
                    video.get("new_title", "")[:37] + "..."
                    if len(video.get("new_title", "")) > 40
                    else video.get("new_title", "")
                ),
                (
                    video.get("original_title", "")[:37] + "..."
                    if len(video.get("original_title", "")) > 40
                    else video.get("original_title", "")
                ),
                video.get("updated_at", "")[:19] if video.get("updated_at") else "",
            )

        console.print(table)
        console.print("\n[dim]Use --rollback <video_id> to rollback a specific video[/dim]")
        console.print("[dim]Use --rollback-all to rollback all videos[/dim]")
