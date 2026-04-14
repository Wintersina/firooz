from __future__ import annotations

from firooz.responses import (
    MILESTONE_EMOJIS,
    SELF_VOTE_ROASTS,
    format_karma_response,
    format_leaderboard,
    format_self_vote_response,
)


class TestFormatKarmaResponse:
    def test_normal_increment(self) -> None:
        result = format_karma_response("Alice", 3, 1)
        assert "Alice" in result
        assert "gained" in result
        assert "3" in result
        assert "MILESTONE" not in result

    def test_normal_decrement(self) -> None:
        result = format_karma_response("Bob", 7, -1)
        assert "Bob" in result
        assert "lost" in result
        assert "7" in result

    def test_milestone_hit(self) -> None:
        for threshold, emoji in MILESTONE_EMOJIS.items():
            result = format_karma_response("Charlie", threshold, 1)
            assert "MILESTONE" in result
            assert emoji in result

    def test_non_milestone(self) -> None:
        result = format_karma_response("Dave", 42, 1)
        assert "MILESTONE" not in result

    def test_with_reason(self) -> None:
        result = format_karma_response("Alice", 3, 1, "for nice link")
        assert "for nice link" in result

    def test_without_reason(self) -> None:
        result = format_karma_response("Alice", 3, 1)
        assert ">" not in result  # no blockquote when no reason


class TestFormatSelfVoteResponse:
    def test_contains_username(self) -> None:
        result = format_self_vote_response("Eve")
        assert "Eve" in result

    def test_is_from_roast_list(self) -> None:
        for _ in range(50):
            result = format_self_vote_response("Eve")
            roast_found = any(roast in result for roast in SELF_VOTE_ROASTS)
            assert roast_found


class TestFormatLeaderboard:
    def test_empty(self) -> None:
        result = format_leaderboard([], "Test Guild")
        assert "No karma" in result

    def test_populated(self) -> None:
        entries = [("Alice", 50), ("Bob", 30), ("Charlie", 10)]
        result = format_leaderboard(entries, "Test Guild")
        assert "Test Guild" in result
        assert "Alice" in result
        assert "50" in result
        assert "\U0001f947" in result  # gold medal for first place

    def test_more_than_three_entries(self) -> None:
        entries = [("A", 40), ("B", 30), ("C", 20), ("D", 10)]
        result = format_leaderboard(entries, "Guild")
        assert "**4.**" in result
