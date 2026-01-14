#!/usr/bin/env python3
"""
Configuration handling for YouTube Boss Title Updater
"""

import copy
import os
from pathlib import Path
from typing import Any, Optional

import yaml


class Config:
    """Configuration manager for the application"""

    DEFAULT_CONFIG = {
        "openai": {
            "api_key": "${OPENAI_API_KEY}",  # Placeholder for environment variable
            "model": "gpt-4o",
            "max_tokens": 100,
        },
        "rawg": {
            "api_key": "${RAWG_API_KEY}",  # Optional: for gaming API integration
        },
        "youtube": {
            "log_spreadsheet_name": "YouTube Boss Title Updates",
            "rate_limit_delay": 2,  # seconds between video processing
        },
        "processing": {
            "frame_extraction": {
                "timestamps": [10, 20, 30, 45, 60],  # seconds
                "quality": "worst",  # video quality for extraction
            },
            "retry": {"max_attempts": 3, "exponential_backoff": True},
            "cache": {"enabled": True, "expiry_days": 30},
            "parallel": {"enabled": False, "workers": 3},
        },
        "soulslike_games": [
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
        ],
    }

    def __init__(self, config_path: Optional[str] = None):
        """Initialize configuration from file or defaults"""
        self.config = copy.deepcopy(self.DEFAULT_CONFIG)

        if config_path:
            self.load_from_file(config_path)

        # Override with environment variables if present
        self._load_from_environment()

    def load_from_file(self, config_path: str):
        """Load configuration from YAML file"""
        path = Path(config_path)

        if not path.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")

        try:
            with open(path) as f:
                user_config = yaml.safe_load(f)

            if user_config:
                self._deep_merge(self.config, user_config)

        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML in configuration file: {e}") from e
        except Exception as e:
            raise ValueError(f"Error loading configuration file: {e}") from e

    def _deep_merge(self, base: dict, update: dict):
        """Recursively merge update dict into base dict"""
        for key, value in update.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._deep_merge(base[key], value)
            else:
                base[key] = value

    def _load_from_environment(self):
        """Load sensitive values from environment variables, replacing placeholders"""
        self._resolve_env_placeholders(self.config)

    def _resolve_env_placeholders(self, config_dict: dict):
        """Recursively resolve environment variable placeholders in config"""
        for key, value in config_dict.items():
            if isinstance(value, dict):
                self._resolve_env_placeholders(value)
            elif isinstance(value, str) and value.startswith("${") and value.endswith("}"):
                # Extract environment variable name
                env_var = value[2:-1]
                env_value = os.getenv(env_var)
                if env_value:
                    config_dict[key] = env_value
                # If env var not found, keep placeholder (will be caught by validation)

    def validate(self):
        """Validate required configuration values"""
        errors = []

        # Check OpenAI API key
        api_key = self.config["openai"]["api_key"]
        if not api_key or (isinstance(api_key, str) and api_key.startswith("${")):
            errors.append(
                "OpenAI API key is required (set OPENAI_API_KEY environment variable or configure in config file)"
            )

        # Validate frame extraction timestamps
        timestamps = self.config["processing"]["frame_extraction"]["timestamps"]
        if not timestamps or not isinstance(timestamps, list):
            errors.append("Frame extraction timestamps must be a non-empty list")

        # Validate retry attempts
        max_attempts = self.config["processing"]["retry"]["max_attempts"]
        if not isinstance(max_attempts, int) or max_attempts < 1:
            errors.append("Max retry attempts must be a positive integer")

        if errors:
            raise ValueError("Configuration validation failed:\n" + "\n".join(f"  - {e}" for e in errors))

        return True

    def get(self, key_path: str, default: Any = None) -> Any:
        """
        Get a configuration value using dot notation
        Example: config.get('openai.api_key')
        """
        keys = key_path.split(".")
        value = self.config

        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default

        return value

    def __getitem__(self, key: str) -> Any:
        """Allow dict-like access to config"""
        return self.config[key]


def create_example_config(output_path: str = "config.yml.example"):
    """Create an example configuration file"""
    example_config = """# YouTube Boss Title Updater Configuration
# Copy this file to config.yml and customize as needed

# OpenAI Configuration
openai:
  # Use placeholder for environment variable (default)
  api_key: "${OPENAI_API_KEY}"
  # Or set directly (not recommended for security)
  # api_key: "sk-..."
  model: "gpt-4o"
  max_tokens: 100

# RAWG Gaming API Configuration (Optional)
# Get your free API key at https://rawg.io/apidocs
rawg:
  api_key: "${RAWG_API_KEY}"
  # Or set directly
  # api_key: "your-rawg-api-key"

# YouTube Configuration
youtube:
  log_spreadsheet_name: "YouTube Boss Title Updates"
  rate_limit_delay: 2  # seconds between video processing

# Processing Configuration
processing:
  # Frame extraction settings
  frame_extraction:
    timestamps: [10, 20, 30, 45, 60]  # seconds into video to extract frames
    quality: "worst"  # video quality for extraction (worst/best)

  # Retry settings for API failures
  retry:
    max_attempts: 3
    exponential_backoff: true

  # Caching settings
  cache:
    enabled: true
    expiry_days: 30  # cache entries expire after 30 days

  # Parallel processing settings
  parallel:
    enabled: false  # enable parallel processing
    workers: 3  # number of concurrent workers

# List of souls-like games that should get "Melee" tag
soulslike_games:
  - bloodborne
  - dark souls
  - demon's souls
  - demons souls
  - elden ring
  - sekiro
  - lords of the fallen
  - lies of p
  - nioh
  - mortal shell
  - salt and sanctuary
  - hollow knight
  - the surge
  - remnant
"""

    with open(output_path, "w") as f:
        f.write(example_config)

    print(f"Created example configuration file: {output_path}")


if __name__ == "__main__":
    # Create example config when run directly
    create_example_config()
