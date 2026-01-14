#!/usr/bin/env python3
"""
Boss List Scraper for YouTube Boss Title Updater
Scrapes boss names from Wikipedia and Fandom wikis
"""

import json
import logging
import time
from pathlib import Path
from typing import Optional
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup


class BossScraper:
    """
    Web scraper for extracting boss lists from gaming wikis

    Supports:
    - Wikipedia
    - Fandom wikis (various game-specific wikis)
    """

    # User agent to identify our scraper (polite web scraping practice)
    USER_AGENT = "YouTubeBossTitleUpdater/1.1 (Educational project; +https://github.com/timbroder/YouTubeBossTitles)"

    # Rate limiting: minimum delay between requests (seconds)
    REQUEST_DELAY = 2.0

    # Wiki URL patterns
    FANDOM_DOMAINS = {
        "bloodborne": "https://bloodborne.fandom.com",
        "darksouls": "https://darksouls.fandom.com",
        "darksouls3": "https://darksouls3.fandom.com",
        "eldenring": "https://eldenring.fandom.com",
        "sekiro": "https://sekiroshadowsdietwice.fandom.com",
        "nioh": "https://nioh.fandom.com",
        "liesofp": "https://liesofp.fandom.com",
    }

    def __init__(self, cache_dir: str = "boss_lists", logger: Optional[logging.Logger] = None):
        """
        Initialize boss scraper

        Args:
            cache_dir: Directory to store cached boss lists
            logger: Optional logger instance

        Example:
            >>> scraper = BossScraper()
            >>> bosses = scraper.get_boss_list("Bloodborne")
            >>> print(f"Found {len(bosses)} bosses")
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        self.logger = logger or logging.getLogger(__name__)
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.USER_AGENT})
        self._last_request_time = 0

    def _rate_limit(self) -> None:
        """
        Enforce rate limiting between requests

        Ensures we wait at least REQUEST_DELAY seconds between requests
        to be polite to web servers
        """
        elapsed = time.time() - self._last_request_time
        if elapsed < self.REQUEST_DELAY:
            sleep_time = self.REQUEST_DELAY - elapsed
            self.logger.debug(f"Rate limiting: sleeping for {sleep_time:.2f}s")
            time.sleep(sleep_time)
        self._last_request_time = time.time()

    def _fetch_url(self, url: str) -> Optional[str]:
        """
        Fetch URL content with error handling and rate limiting

        Args:
            url: URL to fetch

        Returns:
            HTML content as string, or None if request fails
        """
        self._rate_limit()

        try:
            self.logger.info(f"Fetching URL: {url}")
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            return response.text
        except requests.RequestException as e:
            self.logger.error(f"Failed to fetch {url}: {e}")
            return None

    def _get_cache_path(self, game_name: str) -> Path:
        """
        Get cache file path for a game

        Args:
            game_name: Name of the game

        Returns:
            Path to cache file
        """
        safe_name = "".join(c if c.isalnum() else "_" for c in game_name.lower())
        return self.cache_dir / f"{safe_name}.json"

    def _load_from_cache(self, game_name: str) -> Optional[list[str]]:
        """
        Load boss list from cache

        Args:
            game_name: Name of the game

        Returns:
            List of boss names, or None if not cached
        """
        cache_path = self._get_cache_path(game_name)

        if not cache_path.exists():
            return None

        try:
            with open(cache_path) as f:
                data = json.load(f)
                self.logger.info(f"Loaded {len(data['bosses'])} bosses from cache for {game_name}")
                return data["bosses"]
        except (json.JSONDecodeError, KeyError, OSError) as e:
            self.logger.error(f"Failed to load cache for {game_name}: {e}")
            return None

    def _save_to_cache(self, game_name: str, bosses: list[str]) -> bool:
        """
        Save boss list to cache

        Args:
            game_name: Name of the game
            bosses: List of boss names

        Returns:
            True if saved successfully
        """
        cache_path = self._get_cache_path(game_name)

        try:
            data = {"game": game_name, "bosses": bosses, "cached_at": time.strftime("%Y-%m-%d %H:%M:%S")}

            with open(cache_path, "w") as f:
                json.dump(data, f, indent=2)

            self.logger.info(f"Cached {len(bosses)} bosses for {game_name}")
            return True
        except OSError as e:
            self.logger.error(f"Failed to save cache for {game_name}: {e}")
            return False

    def scrape_wikipedia(self, game_name: str) -> list[str]:
        """
        Scrape boss list from Wikipedia

        Args:
            game_name: Name of the game

        Returns:
            List of boss names found on Wikipedia

        Example:
            >>> scraper = BossScraper()
            >>> bosses = scraper.scrape_wikipedia("Bloodborne")
        """
        # Construct Wikipedia search URL
        search_url = f"https://en.wikipedia.org/wiki/{quote(game_name.replace(' ', '_'))}"

        html = self._fetch_url(search_url)
        if not html:
            return []

        soup = BeautifulSoup(html, "lxml")
        bosses = []

        # Look for sections that might contain boss information
        # Common section headers: "Bosses", "Enemies", "Boss Battles"
        for heading in soup.find_all(["h2", "h3", "h4"]):
            heading_text = heading.get_text().lower()

            if any(keyword in heading_text for keyword in ["boss", "enemy", "creature"]):
                # Find the next list after this heading
                next_elem = heading.find_next_sibling()

                while next_elem and next_elem.name not in ["h2", "h3", "h4"]:
                    if next_elem.name in ["ul", "ol"]:
                        for item in next_elem.find_all("li"):
                            boss_name = item.get_text().strip()
                            # Clean up text (remove citations, parentheticals)
                            boss_name = boss_name.split("[")[0].strip()
                            boss_name = boss_name.split("(")[0].strip()

                            if boss_name and len(boss_name) > 2:
                                bosses.append(boss_name)

                    next_elem = next_elem.find_next_sibling()

        # Also check tables for boss information
        for table in soup.find_all("table", class_="wikitable"):
            for row in table.find_all("tr")[1:]:  # Skip header row
                cells = row.find_all(["td", "th"])
                if cells:
                    boss_name = cells[0].get_text().strip()
                    boss_name = boss_name.split("[")[0].strip()
                    boss_name = boss_name.split("(")[0].strip()

                    if boss_name and len(boss_name) > 2:
                        bosses.append(boss_name)

        # Remove duplicates while preserving order
        unique_bosses = []
        seen = set()
        for boss in bosses:
            if boss.lower() not in seen:
                unique_bosses.append(boss)
                seen.add(boss.lower())

        self.logger.info(f"Found {len(unique_bosses)} bosses on Wikipedia for {game_name}")
        return unique_bosses

    def scrape_fandom(self, game_name: str) -> list[str]:
        """
        Scrape boss list from Fandom wiki

        Args:
            game_name: Name of the game

        Returns:
            List of boss names found on Fandom wiki

        Example:
            >>> scraper = BossScraper()
            >>> bosses = scraper.scrape_fandom("Bloodborne")
        """
        # Determine which Fandom wiki to use
        game_lower = game_name.lower().replace(" ", "").replace(":", "").replace("'", "")

        base_url = None
        for key, url in self.FANDOM_DOMAINS.items():
            if key in game_lower:
                base_url = url
                break

        if not base_url:
            self.logger.debug(f"No Fandom wiki configured for {game_name}")
            return []

        # Try common boss list page URLs
        possible_pages = ["Bosses", "Boss", "Boss_Battles", "List_of_Bosses", "Category:Bosses"]

        all_bosses = []

        for page in possible_pages:
            url = urljoin(base_url, f"/wiki/{page}")
            html = self._fetch_url(url)

            if not html:
                continue

            soup = BeautifulSoup(html, "lxml")
            bosses = []

            # Look for boss names in various structures
            # Method 1: Category page with gallery
            for item in soup.find_all("div", class_="category-page__member"):
                link = item.find("a", class_="category-page__member-link")
                if link:
                    boss_name = link.get("title", "").strip()
                    if boss_name:
                        bosses.append(boss_name)

            # Method 2: Lists on the page
            for ul in soup.find_all("ul"):
                for li in ul.find_all("li"):
                    link = li.find("a")
                    if link:
                        boss_name = link.get_text().strip()
                        # Filter out navigation/meta links
                        if boss_name and not boss_name.startswith("File:") and len(boss_name) > 2:
                            bosses.append(boss_name)

            # Method 3: Tables
            for table in soup.find_all("table"):
                for row in table.find_all("tr")[1:]:  # Skip header
                    cells = row.find_all(["td", "th"])
                    if cells:
                        link = cells[0].find("a")
                        if link:
                            boss_name = link.get_text().strip()
                            if boss_name and len(boss_name) > 2:
                                bosses.append(boss_name)

            if bosses:
                all_bosses.extend(bosses)
                self.logger.info(f"Found {len(bosses)} bosses on Fandom page: {page}")

        # Remove duplicates while preserving order
        unique_bosses = []
        seen = set()
        for boss in all_bosses:
            if boss.lower() not in seen:
                unique_bosses.append(boss)
                seen.add(boss.lower())

        self.logger.info(f"Total {len(unique_bosses)} unique bosses found on Fandom for {game_name}")
        return unique_bosses

    def get_boss_list(self, game_name: str, use_cache: bool = True) -> list[str]:
        """
        Get comprehensive boss list for a game

        Tries cache first, then scrapes from multiple sources and combines results

        Args:
            game_name: Name of the game
            use_cache: Whether to use cached results (default: True)

        Returns:
            List of boss names

        Example:
            >>> scraper = BossScraper()
            >>> bosses = scraper.get_boss_list("Elden Ring")
            >>> for boss in bosses:
            ...     print(f"- {boss}")
        """
        # Check cache first
        if use_cache:
            cached = self._load_from_cache(game_name)
            if cached:
                return cached

        # Scrape from multiple sources
        all_bosses = []

        # Try Wikipedia
        wikipedia_bosses = self.scrape_wikipedia(game_name)
        all_bosses.extend(wikipedia_bosses)

        # Try Fandom
        fandom_bosses = self.scrape_fandom(game_name)
        all_bosses.extend(fandom_bosses)

        # Remove duplicates while preserving order
        unique_bosses = []
        seen = set()
        for boss in all_bosses:
            if boss.lower() not in seen:
                unique_bosses.append(boss)
                seen.add(boss.lower())

        # Save to cache
        if unique_bosses:
            self._save_to_cache(game_name, unique_bosses)

        self.logger.info(f"Total {len(unique_bosses)} unique bosses found for {game_name}")
        return unique_bosses

    def clear_cache(self, game_name: Optional[str] = None) -> int:
        """
        Clear cached boss lists

        Args:
            game_name: Specific game to clear, or None to clear all

        Returns:
            Number of cache files cleared
        """
        if game_name:
            cache_path = self._get_cache_path(game_name)
            if cache_path.exists():
                cache_path.unlink()
                self.logger.info(f"Cleared cache for {game_name}")
                return 1
            return 0

        # Clear all cache files
        count = 0
        for cache_file in self.cache_dir.glob("*.json"):
            cache_file.unlink()
            count += 1

        self.logger.info(f"Cleared {count} cache files")
        return count

    def get_cached_games(self) -> list[str]:
        """
        Get list of games with cached boss lists

        Returns:
            List of game names that have cached data
        """
        games = []
        for cache_file in self.cache_dir.glob("*.json"):
            try:
                with open(cache_file) as f:
                    data = json.load(f)
                    games.append(data.get("game", cache_file.stem))
            except (json.JSONDecodeError, OSError):
                continue

        return games
