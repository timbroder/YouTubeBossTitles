#!/usr/bin/env python3
"""
Gaming API integration for YouTube Boss Title Updater
Provides game metadata from RAWG API with caching
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Optional

import requests


class GamingAPI:
    """
    Integration with RAWG.io gaming database API

    RAWG API Documentation: https://api.rawg.io/docs/
    To get an API key: https://rawg.io/apidocs
    """

    # Hardcoded fallback list of souls-like games
    SOULSLIKE_GAMES_FALLBACK = [
        "bloodborne",
        "dark souls",
        "demon's souls",
        "demons souls",
        "elden ring",
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

    # Tags that indicate a souls-like game
    SOULSLIKE_TAGS = [
        "souls-like",
        "soulslike",
        "dark souls",
        "difficult",
        "challenging",
        "action rpg",
        "third person",
        "dark fantasy",
    ]

    def __init__(
        self, api_key: Optional[str] = None, cache_expiry_days: int = 30, logger: Optional[logging.Logger] = None
    ):
        """
        Initialize Gaming API client

        Args:
            api_key: RAWG API key (or set RAWG_API_KEY environment variable)
            cache_expiry_days: Number of days to cache API responses
            logger: Optional logger instance

        Example:
            >>> api = GamingAPI(api_key="your-api-key")
            >>> is_soulslike = api.is_soulslike_game("Elden Ring")
        """
        self.api_key = api_key or os.getenv("RAWG_API_KEY")
        self.base_url = "https://api.rawg.io/api"
        self.cache_expiry_days = cache_expiry_days
        self.logger = logger or logging.getLogger(__name__)

        # In-memory cache for API responses
        self._cache: dict[str, tuple[dict, datetime]] = {}

        if not self.api_key:
            self.logger.warning(
                "RAWG API key not provided. Will use fallback list for souls-like detection. "
                "Get an API key at https://rawg.io/apidocs"
            )

    def _make_request(self, endpoint: str, params: Optional[dict] = None) -> Optional[dict]:
        """
        Make a request to RAWG API with error handling

        Args:
            endpoint: API endpoint (e.g., "games")
            params: Query parameters

        Returns:
            API response as dict, or None if request fails
        """
        if not self.api_key:
            self.logger.debug("No API key available, skipping API request")
            return None

        url = f"{self.base_url}/{endpoint}"
        params = params or {}
        params["key"] = self.api_key

        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            self.logger.error(f"RAWG API request failed: {e}")
            return None

    def _get_cached(self, cache_key: str) -> Optional[dict]:
        """
        Get cached API response if not expired

        Args:
            cache_key: Cache key

        Returns:
            Cached data or None if not found/expired
        """
        if cache_key in self._cache:
            data, timestamp = self._cache[cache_key]
            expiry = timestamp + timedelta(days=self.cache_expiry_days)

            if datetime.now() < expiry:
                self.logger.debug(f"Cache hit for key: {cache_key}")
                return data
            else:
                # Remove expired entry
                del self._cache[cache_key]
                self.logger.debug(f"Cache expired for key: {cache_key}")

        return None

    def _set_cache(self, cache_key: str, data: dict) -> None:
        """
        Store data in cache

        Args:
            cache_key: Cache key
            data: Data to cache
        """
        self._cache[cache_key] = (data, datetime.now())
        self.logger.debug(f"Cached data for key: {cache_key}")

    def search_game(self, game_name: str) -> Optional[dict]:
        """
        Search for a game by name

        Args:
            game_name: Name of the game to search

        Returns:
            Game metadata dict or None if not found

        Example:
            >>> api = GamingAPI()
            >>> game = api.search_game("Elden Ring")
            >>> if game:
            ...     print(f"Found: {game['name']}")
        """
        cache_key = f"game:{game_name.lower()}"

        # Check cache first
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        # Make API request
        self.logger.info(f"Searching RAWG API for game: {game_name}")
        response = self._make_request("games", {"search": game_name, "page_size": 1})

        if not response or not response.get("results"):
            self.logger.debug(f"No results found for game: {game_name}")
            return None

        # Get first result
        game = response["results"][0]

        # Cache the result
        self._set_cache(cache_key, game)

        return game

    def get_game_details(self, game_id: int) -> Optional[dict]:
        """
        Get detailed information about a game

        Args:
            game_id: RAWG game ID

        Returns:
            Game details dict or None if not found
        """
        cache_key = f"game_details:{game_id}"

        # Check cache first
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        # Make API request
        self.logger.info(f"Fetching game details for ID: {game_id}")
        game_details = self._make_request(f"games/{game_id}")

        if game_details:
            self._set_cache(cache_key, game_details)

        return game_details

    def is_soulslike_game(self, game_name: str) -> bool:
        """
        Determine if a game is souls-like based on RAWG API data or fallback list

        Args:
            game_name: Name of the game

        Returns:
            True if game is souls-like, False otherwise

        Example:
            >>> api = GamingAPI()
            >>> api.is_soulslike_game("Dark Souls")
            True
            >>> api.is_soulslike_game("Mario Kart")
            False
        """
        game_name_lower = game_name.lower()

        # Check hardcoded fallback list first
        for fallback_game in self.SOULSLIKE_GAMES_FALLBACK:
            if fallback_game in game_name_lower:
                self.logger.info(f"Game '{game_name}' matched fallback souls-like list")
                return True

        # If no API key, use only fallback list
        if not self.api_key:
            return False

        # Search for game via API
        game = self.search_game(game_name)
        if not game:
            self.logger.debug(f"Game '{game_name}' not found in RAWG API")
            return False

        # Check tags
        tags = game.get("tags", [])
        for tag in tags:
            tag_name = tag.get("name", "").lower()
            for soulslike_tag in self.SOULSLIKE_TAGS:
                if soulslike_tag in tag_name:
                    self.logger.info(f"Game '{game_name}' identified as souls-like via tag: {tag_name}")
                    return True

        # Check genres
        genres = game.get("genres", [])
        genre_names = [g.get("name", "").lower() for g in genres]

        # Action RPGs with certain characteristics might be souls-like
        if "action" in str(genre_names) and "rpg" in str(genre_names):
            self.logger.debug(f"Game '{game_name}' is Action RPG, checking further")

            # Get detailed info to check descriptions
            game_id = game.get("id")
            if game_id:
                details = self.get_game_details(game_id)
                if details:
                    description = (details.get("description_raw") or "").lower()

                    # Look for souls-like keywords in description
                    souls_keywords = ["dark souls", "souls-like", "soulslike", "challenging combat", "punishing"]
                    for keyword in souls_keywords:
                        if keyword in description:
                            self.logger.info(
                                f"Game '{game_name}' identified as souls-like via description keyword: {keyword}"
                            )
                            return True

        self.logger.debug(f"Game '{game_name}' not identified as souls-like")
        return False

    def get_game_metadata(self, game_name: str) -> Optional[dict]:
        """
        Get comprehensive metadata for a game

        Args:
            game_name: Name of the game

        Returns:
            Dict with game metadata including:
            - name: Game name
            - released: Release date
            - genres: List of genres
            - tags: List of tags
            - rating: Average rating
            - is_soulslike: Whether game is souls-like

        Example:
            >>> api = GamingAPI()
            >>> metadata = api.get_game_metadata("Bloodborne")
            >>> if metadata:
            ...     print(f"Released: {metadata['released']}")
            ...     print(f"Is Souls-like: {metadata['is_soulslike']}")
        """
        game = self.search_game(game_name)
        if not game:
            return None

        # Build metadata dict
        metadata = {
            "name": game.get("name"),
            "released": game.get("released"),
            "genres": [g.get("name") for g in game.get("genres", [])],
            "tags": [t.get("name") for t in game.get("tags", [])],
            "rating": game.get("rating"),
            "metacritic": game.get("metacritic"),
            "is_soulslike": self.is_soulslike_game(game_name),
        }

        return metadata

    def clear_cache(self) -> int:
        """
        Clear all cached API responses

        Returns:
            Number of entries cleared
        """
        count = len(self._cache)
        self._cache.clear()
        self.logger.info(f"Cleared {count} cached API responses")
        return count

    def get_cache_stats(self) -> dict[str, int]:
        """
        Get cache statistics

        Returns:
            Dict with cache statistics
        """
        now = datetime.now()
        expired = 0

        for _, (_, timestamp) in self._cache.items():
            expiry = timestamp + timedelta(days=self.cache_expiry_days)
            if now >= expiry:
                expired += 1

        return {
            "total": len(self._cache),
            "active": len(self._cache) - expired,
            "expired": expired,
        }
