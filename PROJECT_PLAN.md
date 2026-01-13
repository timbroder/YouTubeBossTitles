# YouTube Boss Title Updater - Project Plan

This document outlines all planned improvements and enhancements for the YouTube Boss Title Updater project.

**Status Legend:**
- 🔴 Not Started
- 🟡 In Progress
- 🟢 Complete

---

## Phase 1: Core Usability Improvements

### 1.1 CLI Arguments & Configuration
**Priority:** High | **Effort:** Medium | **Status:** 🔴

**Tasks:**
- [ ] Add argparse for command-line argument parsing
- [ ] Implement `--dry-run` flag
- [ ] Implement `--config <path>` for custom config file
- [ ] Implement `--video-id <id>` to process specific video
- [ ] Implement `--game <name>` to filter by game
- [ ] Implement `--limit <n>` to process only N videos
- [ ] Implement `--force` to reprocess already-processed videos
- [ ] Create default config.yml template
- [ ] Add config file validation
- [ ] Add `--version` flag
- [ ] Add `--list-games` to show detected games with counts

**Files to modify:**
- `youtube_boss_titles.py` (main function)
- New: `config.py` (configuration handling)
- New: `config.yml.example` (template)

**Example usage:**
```bash
python youtube_boss_titles.py --dry-run --config prod.yml
python youtube_boss_titles.py --video-id abc123 --force
python youtube_boss_titles.py --game "Bloodborne" --limit 5
```

### 1.2 Resume & Recovery System
**Priority:** High | **Effort:** Medium | **Status:** 🔴

**Tasks:**
- [ ] Create local SQLite database for tracking processed videos
- [ ] Store processing state (pending, processing, completed, failed)
- [ ] Check Google Sheets log before processing (avoid duplicates)
- [ ] Add `--resume` flag to continue from last run
- [ ] Store partial results on crash
- [ ] Implement retry logic with exponential backoff for API failures
- [ ] Add max retry configuration (default: 3)
- [ ] Store failed videos separately for later retry

**Files to modify:**
- New: `database.py` (SQLite operations)
- New: `processed_videos.db` (database file, add to .gitignore)
- `youtube_boss_titles.py` (integrate database checks)

**Database Schema:**
```sql
CREATE TABLE processed_videos (
    video_id TEXT PRIMARY KEY,
    original_title TEXT,
    new_title TEXT,
    game_name TEXT,
    boss_name TEXT,
    status TEXT, -- pending, processing, completed, failed
    attempts INTEGER DEFAULT 0,
    last_attempt TIMESTAMP,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 1.3 Progress Tracking & UI
**Priority:** High | **Effort:** Small | **Status:** 🔴

**Tasks:**
- [ ] Add `rich` library to requirements.txt
- [ ] Implement progress bar with `rich.progress`
- [ ] Show real-time statistics (processed, failed, skipped)
- [ ] Display estimated time remaining
- [ ] Add colored output for different message types
- [ ] Show cost estimation before starting
- [ ] Add summary report at the end

**Files to modify:**
- `requirements.txt` (add rich)
- `youtube_boss_titles.py` (integrate rich progress bars)

---

## Phase 2: Enhanced Boss Detection

### 2.1 Gaming API Integration
**Priority:** Medium | **Effort:** Medium | **Status:** 🔴

**Tasks:**
- [ ] Implement RAWG API integration
- [ ] Fetch game metadata (genre, tags, release date)
- [ ] Use API to detect souls-like games dynamically
- [ ] Cache API responses to reduce calls
- [ ] Implement fallback to hardcoded list

**Files to modify:**
- New: `gaming_api.py` (API integration)
- `youtube_boss_titles.py` (replace is_soulslike logic)

### 2.2 Boss List Scraping
**Priority:** Medium | **Effort:** Large | **Status:** 🔴

**Tasks:**
- [ ] Implement Wikipedia scraping for boss lists
- [ ] Implement Fandom wiki scraping
- [ ] Add BeautifulSoup4 to requirements
- [ ] Cache scraped boss lists locally (JSON files)
- [ ] Add boss list to OpenAI prompt for better context
- [ ] Handle rate limiting and politeness delays
- [ ] Add user-agent headers

**Files to modify:**
- `requirements.txt` (add beautifulsoup4, lxml)
- New: `boss_scraper.py` (web scraping)
- New: `boss_lists/` directory (cached boss data)
- `youtube_boss_titles.py` (integrate boss lists)

### 2.3 Confidence Scoring
**Priority:** Low | **Effort:** Small | **Status:** 🔴

**Tasks:**
- [ ] Modify OpenAI prompt to return confidence score
- [ ] Parse confidence from response
- [ ] Store confidence in database
- [ ] Add `--min-confidence <0.0-1.0>` flag
- [ ] Log low-confidence identifications for manual review

**Files to modify:**
- `youtube_boss_titles.py` (OpenAI integration)
- `database.py` (add confidence column)

### 2.4 Manual Review Mode
**Priority:** Medium | **Effort:** Medium | **Status:** 🔴

**Tasks:**
- [ ] Add `--review` flag for manual approval
- [ ] Show video thumbnail and detected boss name
- [ ] Prompt for user confirmation (y/n/skip/edit)
- [ ] Allow manual boss name entry
- [ ] Save user corrections for future learning
- [ ] Show video URL for quick access

**Files to modify:**
- `youtube_boss_titles.py` (add review mode)

---

## Phase 3: Error Handling & Monitoring

### 3.1 Structured Logging
**Priority:** Medium | **Effort:** Small | **Status:** 🔴

**Tasks:**
- [ ] Replace print statements with logging module
- [ ] Implement JSON logging format
- [ ] Create separate log files (info.log, error.log)
- [ ] Add log rotation (max size 10MB, keep 5 files)
- [ ] Configure log levels via CLI or config
- [ ] Add request/response logging for debugging

**Files to modify:**
- New: `logging_config.py`
- `youtube_boss_titles.py` (replace all print statements)

### 3.2 Enhanced Error Tracking
**Priority:** Medium | **Effort:** Small | **Status:** 🔴

**Tasks:**
- [ ] Add error details column to Google Sheets
- [ ] Add error_type column (api_failure, video_not_found, etc.)
- [ ] Create separate "Errors" sheet tab
- [ ] Log stack traces for unexpected errors
- [ ] Add error frequency tracking

**Files to modify:**
- `youtube_boss_titles.py` (sheets integration)

### 3.3 Notification System
**Priority:** Low | **Effort:** Medium | **Status:** 🔴

**Tasks:**
- [ ] Add optional Discord webhook support
- [ ] Add optional email notification support (via SMTP)
- [ ] Notify on completion with summary
- [ ] Notify on errors/failures
- [ ] Add `--notify discord` and `--notify email` flags
- [ ] Create notification templates

**Files to modify:**
- New: `notifications.py`
- `youtube_boss_titles.py` (integrate notifications)
- `config.yml` (add notification settings)

---

## Phase 4: Performance Optimization

### 4.1 Parallel Processing
**Priority:** Medium | **Effort:** Medium | **Status:** 🔴

**Tasks:**
- [ ] Implement ThreadPoolExecutor for concurrent video processing
- [ ] Add `--workers <n>` flag (default: 3)
- [ ] Handle thread-safe database writes
- [ ] Handle thread-safe Google Sheets writes
- [ ] Add rate limiting per thread
- [ ] Test with different worker counts

**Files to modify:**
- `youtube_boss_titles.py` (add threading)

### 4.2 Caching System
**Priority:** Medium | **Effort:** Small | **Status:** 🔴

**Tasks:**
- [ ] Cache OpenAI responses (video_id -> boss_name)
- [ ] Cache thumbnail URLs
- [ ] Cache gaming API responses
- [ ] Add cache expiry (default: 30 days)
- [ ] Add `--clear-cache` flag
- [ ] Use SQLite for cache storage

**Files to modify:**
- `database.py` (add cache tables)
- `youtube_boss_titles.py` (check cache before API calls)

### 4.3 Optimize Frame Extraction
**Priority:** Low | **Effort:** Small | **Status:** 🔴

**Tasks:**
- [ ] Add configurable frame count (default: 5)
- [ ] Add configurable frame quality (default: medium)
- [ ] Test with 3 frames vs 5 frames accuracy
- [ ] Allow per-game timestamp configuration

**Files to modify:**
- `config.yml` (add frame settings)
- `youtube_boss_titles.py` (use config values)

### 4.4 Batch API Calls
**Priority:** Low | **Effort:** Medium | **Status:** 🔴

**Tasks:**
- [ ] Research YouTube API batch endpoints
- [ ] Batch playlist operations where possible
- [ ] Reduce API calls by fetching more data per request

**Files to modify:**
- `youtube_boss_titles.py` (YouTube API calls)

---

## Phase 5: Data Management

### 5.1 Undo/Rollback System
**Priority:** Medium | **Effort:** Medium | **Status:** 🔴

**Tasks:**
- [ ] Store original titles in database before updating
- [ ] Implement `--rollback <video_id>` command
- [ ] Implement `--rollback-all` command
- [ ] Add confirmation prompt for rollbacks
- [ ] Update Google Sheets with rollback log

**Files to modify:**
- `database.py` (store original data)
- New: `rollback.py` (rollback logic)
- `youtube_boss_titles.py` (add rollback commands)

### 5.2 Audit Trail
**Priority:** Low | **Effort:** Small | **Status:** 🔴

**Tasks:**
- [ ] Log all changes with timestamps
- [ ] Track who made changes (system vs manual)
- [ ] Add change reason field
- [ ] Export audit log to CSV

**Files to modify:**
- `database.py` (add audit table)
- New: `audit.py` (audit trail logic)

### 5.3 Backup System
**Priority:** Low | **Effort:** Small | **Status:** 🔴

**Tasks:**
- [ ] Auto-backup database before major operations
- [ ] Export current state to JSON
- [ ] Add `--export` command
- [ ] Add `--import` command for restoring

**Files to modify:**
- New: `backup.py`
- `youtube_boss_titles.py` (integrate backups)

---

## Phase 6: Code Quality & Maintainability

### 6.1 Type Hints & Documentation
**Priority:** Medium | **Effort:** Medium | **Status:** 🔴

**Tasks:**
- [ ] Add complete type hints to all functions
- [ ] Add docstring examples to all public methods
- [ ] Configure mypy for type checking
- [ ] Add mypy to GitHub Actions
- [ ] Generate API documentation with Sphinx

**Files to modify:**
- All `.py` files (add type hints)
- New: `docs/` directory
- `.github/workflows/tests.yml` (add mypy)

### 6.2 Pre-commit Hooks
**Priority:** Low | **Effort:** Small | **Status:** 🔴

**Tasks:**
- [ ] Add pre-commit framework
- [ ] Configure black for formatting
- [ ] Configure ruff for linting
- [ ] Configure mypy for type checking
- [ ] Add pre-commit to documentation

**Files to modify:**
- New: `.pre-commit-config.yaml`
- `requirements.txt` (add dev dependencies)

### 6.3 Increase Test Coverage
**Priority:** Medium | **Effort:** Large | **Status:** 🔴

**Tasks:**
- [ ] Add tests for new CLI arguments
- [ ] Add tests for resume/recovery system
- [ ] Add tests for caching
- [ ] Add tests for parallel processing
- [ ] Target 90%+ code coverage
- [ ] Add integration tests for full workflows

**Files to modify:**
- `test_youtube_boss_titles.py` (expand tests)

### 6.4 Code Refactoring
**Priority:** Low | **Effort:** Medium | **Status:** 🔴

**Tasks:**
- [ ] Split YouTubeBossUpdater into smaller classes
- [ ] Extract API clients (YouTube, OpenAI, Sheets)
- [ ] Create separate modules for concerns
- [ ] Apply SOLID principles
- [ ] Reduce method complexity (max 15 lines per method)

**Files to modify:**
- Refactor `youtube_boss_titles.py` into multiple modules
- New: `clients/` directory (API clients)
- New: `models/` directory (data models)
- New: `services/` directory (business logic)

---

## Phase 7: Deployment & Infrastructure

### 7.1 Docker Containerization
**Priority:** Low | **Effort:** Medium | **Status:** 🔴

**Tasks:**
- [ ] Create Dockerfile
- [ ] Create docker-compose.yml
- [ ] Include ffmpeg in container
- [ ] Add volume mounts for config and data
- [ ] Document Docker usage in README
- [ ] Publish to Docker Hub

**Files to modify:**
- New: `Dockerfile`
- New: `docker-compose.yml`
- New: `.dockerignore`
- `README.md` (add Docker section)

### 7.2 Scheduled Runs
**Priority:** Low | **Effort:** Small | **Status:** 🔴

**Tasks:**
- [ ] Create GitHub Actions workflow for scheduled runs
- [ ] Add cron schedule (e.g., daily at 2 AM)
- [ ] Use repository secrets for API keys
- [ ] Send notifications on completion
- [ ] Add manual trigger option

**Files to modify:**
- New: `.github/workflows/scheduled-run.yml`
- `README.md` (document scheduled runs)

### 7.3 Environment-based Configuration
**Priority:** Low | **Effort:** Small | **Status:** 🔴

**Tasks:**
- [ ] Support dev/staging/prod environments
- [ ] Create separate config files per environment
- [ ] Add environment detection
- [ ] Use environment variables for secrets

**Files to modify:**
- New: `config.dev.yml`, `config.prod.yml`
- New: `environment.py` (environment detection)

### 7.4 Secrets Management
**Priority:** Low | **Effort:** Small | **Status:** 🔴

**Tasks:**
- [ ] Research secrets management options
- [ ] Integrate with GitHub Secrets (for CI/CD)
- [ ] Support local .env files (development)
- [ ] Add secrets validation

**Files to modify:**
- `youtube_boss_titles.py` (load secrets securely)

---

## Phase 8: Advanced Features

### 8.1 Video Description Updates
**Priority:** Low | **Effort:** Small | **Status:** 🔴

**Tasks:**
- [ ] Add option to update video descriptions
- [ ] Include boss information in description
- [ ] Add timestamp links
- [ ] Template system for descriptions

**Files to modify:**
- `youtube_boss_titles.py` (add description updates)

### 8.2 Thumbnail Management
**Priority:** Low | **Effort:** Medium | **Status:** 🔴

**Tasks:**
- [ ] Extract best frame as thumbnail
- [ ] Upload custom thumbnail
- [ ] Add boss name overlay to thumbnail

**Files to modify:**
- New: `thumbnail_generator.py`
- `requirements.txt` (add PIL/Pillow)

### 8.5 Bulk Operations
**Priority:** Low | **Effort:** Small | **Status:** 🔴

**Tasks:**
- [ ] Add `--playlist <id>` to process specific playlist
- [ ] Add `--date-range` to filter by upload date
- [ ] Add `--reprocess-failed` to retry failed videos

**Files to modify:**
- `youtube_boss_titles.py` (add filtering)

---

## Phase 9: Monitoring & Analytics

### 9.1 Dashboard/UI
**Priority:** Low | **Effort:** Large | **Status:** 🔴

**Tasks:**
- [ ] Create Flask web interface
- [ ] Show processing statistics
- [ ] Display recent updates
- [ ] Manual video submission
- [ ] Configuration UI

**Files to modify:**
- New: `web/` directory (Flask app)
- New: `templates/` directory (HTML templates)
- New: `static/` directory (CSS, JS)

### 9.2 Cost Tracking
**Priority:** Low | **Effort:** Small | **Status:** 🔴

**Tasks:**
- [ ] Track OpenAI API costs per video
- [ ] Calculate total costs
- [ ] Add cost projections
- [ ] Export cost report

**Files to modify:**
- `database.py` (add cost tracking)
- New: `cost_calculator.py`

### 9.3 Success Rate Metrics
**Priority:** Low | **Effort:** Small | **Status:** 🔴

**Tasks:**
- [ ] Track successful identifications
- [ ] Track failures by type
- [ ] Calculate success rate per game
- [ ] Generate metrics report

**Files to modify:**
- New: `metrics.py`
- `database.py` (add metrics queries)

### 9.4 Accuracy Tracking
**Priority:** Low | **Effort:** Medium | **Status:** 🔴

**Tasks:**
- [ ] Allow user feedback on accuracy
- [ ] Track corrections made in manual review
- [ ] Calculate accuracy over time
- [ ] Identify games with low accuracy

**Files to modify:**
- `database.py` (add feedback table)
- New: `accuracy_tracker.py`

---

## Phase 10: Integration & Extensibility

### 10.1 Discord Bot
**Priority:** Low | **Effort:** Large | **Status:** 🔴

**Tasks:**
- [ ] Create Discord bot for manual approvals
- [ ] Send notifications to Discord channel
- [ ] Allow commands (!process, !status, !rollback)
- [ ] Interactive approval buttons

**Files to modify:**
- New: `discord_bot.py`
- `requirements.txt` (add discord.py)

### 10.2 Notion Integration
**Priority:** Low | **Effort:** Medium | **Status:** 🔴

**Tasks:**
- [ ] Create Notion database for logging
- [ ] Sync Google Sheets to Notion
- [ ] Add rich media (thumbnails, videos)

**Files to modify:**
- New: `notion_integration.py`
- `requirements.txt` (add notion-client)

### 10.3 Plugin System
**Priority:** Low | **Effort:** Large | **Status:** 🔴

**Tasks:**
- [ ] Design plugin architecture
- [ ] Create plugin interface
- [ ] Support custom boss identification methods
- [ ] Support custom title formatters
- [ ] Document plugin development

**Files to modify:**
- New: `plugins/` directory
- New: `plugin_manager.py`

---

## Quick Wins (Can be done in < 2 hours each)

### QW1: Version Flag
**Status:** 🔴

**Tasks:**
- [ ] Add `__version__` to module
- [ ] Add `--version` flag to CLI
- [ ] Display version on startup

### QW2: Better Error Messages
**Status:** 🔴

**Tasks:**
- [ ] Add helpful hints to error messages
- [ ] Include troubleshooting links
- [ ] Add error codes

### QW3: Cost Estimation
**Status:** 🔴

**Tasks:**
- [ ] Calculate estimated cost before running
- [ ] Show breakdown (thumbnail vs full extraction)
- [ ] Add confirmation prompt if cost > threshold

### QW4: Verbose Mode
**Status:** 🔴

**Tasks:**
- [ ] Add `--verbose` flag for detailed output
- [ ] Add `--quiet` flag for minimal output

### QW5: Skip Already Processed
**Status:** 🔴

**Tasks:**
- [ ] Check Google Sheets before processing
- [ ] Skip videos already logged
- [ ] Add `--reprocess` to override

---

## Dependencies Between Tasks

```
Phase 1.2 (Resume System) → Requires Phase 1.1 (CLI Args)
Phase 2.3 (Confidence) → Requires Phase 2.1 (Gaming API)
Phase 4.1 (Parallel) → Requires Phase 3.1 (Logging)
Phase 5.1 (Rollback) → Requires Phase 1.2 (Database)
Phase 7.2 (Scheduled) → Requires Phase 7.3 (Environments)
Phase 9.1 (Dashboard) → Requires Phase 1.2 (Database)
```

---

## Recommended Implementation Order

**Sprint 1 (Foundation):**
1. Phase 1.1 - CLI Arguments
2. Phase 1.2 - Resume System
3. Phase 1.3 - Progress Tracking

**Sprint 2 (Reliability):**
4. Phase 3.1 - Structured Logging
5. Phase 3.2 - Error Tracking
6. Quick Wins (QW1-QW5)

**Sprint 3 (Performance):**
7. Phase 4.2 - Caching
8. Phase 4.1 - Parallel Processing

**Sprint 4 (Quality):**
9. Phase 6.1 - Type Hints
10. Phase 6.3 - Test Coverage
11. Phase 6.2 - Pre-commit Hooks

**Sprint 5 (Features):**
12. Phase 2.1 - Gaming API
13. Phase 2.2 - Boss Scraping
14. Phase 5.1 - Rollback System

**Later Sprints:**
- Advanced features as needed
- Monitoring & analytics
- Deployment improvements

---

## Estimated Effort Summary

- **High Priority + High Impact:** ~3-4 weeks
- **Medium Priority:** ~4-6 weeks
- **Low Priority:** ~6-8 weeks
- **Total:** ~4-5 months for all features

---

## Notes

- Remove any items you don't want by deleting the section
- Adjust priorities based on your needs
- Some items can be done in parallel
- Quick wins can be done anytime for immediate value
