"""
Unit tests for forum mentions functionality in freelance pipeline.

This test verifies the specific forum mentions handling logic that was discussed.
"""

import pytest
from unittest.mock import Mock, patch
import json
import os
from pathlib import Path

# Import the actual modules we need to test
from growth.forums.harvest import (
    iter_forum_signals,
    rank_for_theme,
    render_candidates_md,
    _repo_roots
)

def test_repo_roots_function():
    """Test the _repo_roots function"""
    growth_root, repo_root = _repo_roots()

    assert isinstance(growth_root, Path)
    assert isinstance(repo_root, Path)
    assert growth_root.name == "growth"
    assert "Klaravex2.0" in str(repo_root)

def test_iter_forum_signals_empty():
    """Test iter_forum_signals with empty directory"""
    # Test with a non-existent directory
    result = iter_forum_signals(Path("/non/existent/directory"))
    assert isinstance(result, list)
    assert len(result) == 0

def test_rank_for_theme_function():
    """Test the rank_for_theme function with various inputs"""
    rows = [
        {
            "signal_id": "forum-01",
            "scraper": "forum_mentions",
            "excerpt": "HackerNews: How do I get press coverage for my startup?",
            "prospect": "test-prospect",
            "venue_hint": True
        },
        {
            "signal_id": "forum-02",
            "scraper": "forum",
            "excerpt": "r/sysadmin: Best practices for network security",
            "prospect": "test-prospect",
            "venue_hint": True
        }
    ]

    theme = {"slug": "startup", "business": "tech", "consumer": "entrepreneur", "iso_week": 1}

    ranked = rank_for_theme(rows, theme["slug"])

    assert isinstance(ranked, list)
    assert len(ranked) == 2

def test_render_candidates_md():
    """Test rendering of forum candidates markdown"""
    rows = [
        {
            "signal_id": "forum-01",
            "scraper": "forum_mentions",
            "excerpt": "HackerNews: How do I get press coverage for my startup?",
            "prospect": "test-prospect",
            "venue_hint": True
        }
    ]

    theme = {"slug": "startup", "business": "tech", "consumer": "entrepreneur", "iso_week": 1}
    day = "2024-01-01"

    result = render_candidates_md(rows, theme=theme, day=day)

    assert isinstance(result, str)
    assert len(result) > 0
    assert "Forum harvest" in result
    assert "startup" in result

def test_forum_signals_with_different_scraper_types():
    """Test forum signals with different scraper types"""
    # This would typically be tested by actually reading from bundle.json files
    # but we're testing the logic here

    from growth.forums.harvest import _FORUM_SCRAPERS

    assert "forum_mentions" in _FORUM_SCRAPERS
    assert "forum" in _FORUM_SCRAPERS

def test_venue_hint_regex():
    """Test venue hint regex pattern matching"""
    from growth.forums.harvest import _VENUE_HINT

    # Test various forum-related patterns
    test_cases = [
        ("r/sysadmin", True),
        ("reddit", True),
        ("HackerNews", True),
        ("spiceworks", True),
        ("sysadmin", True),
        ("msp", True),
        ("regular text without forum mentions", False),
        ("This is just normal text", False)
    ]

    for text, expected in test_cases:
        match = _VENUE_HINT.search(text)
        if expected:
            assert match is not None, f"Expected venue hint in '{text}'"
        else:
            assert match is None, f"Unexpected venue hint in '{text}'"

if __name__ == "__main__":
    # Run all tests
    pytest.main([__file__, "-v"])