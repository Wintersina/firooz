from __future__ import annotations

from firooz.karma import KarmaAction, is_milestone, get_milestone_tier, parse_karma_actions, MILESTONES


class TestParseKarmaActions:
    def test_single_increment(self) -> None:
        result = parse_karma_actions("<@123>++")
        assert result == [KarmaAction(user_id=123, delta=1, reason="")]

    def test_single_decrement(self) -> None:
        result = parse_karma_actions("<@123>--")
        assert result == [KarmaAction(user_id=123, delta=-1, reason="")]

    def test_nickname_mention_increment(self) -> None:
        result = parse_karma_actions("<@!456>++")
        assert result == [KarmaAction(user_id=456, delta=1, reason="")]

    def test_nickname_mention_decrement(self) -> None:
        result = parse_karma_actions("<@!456>--")
        assert result == [KarmaAction(user_id=456, delta=-1, reason="")]

    def test_multiple_actions(self) -> None:
        result = parse_karma_actions("<@111>++ <@222>--")
        assert result == [
            KarmaAction(user_id=111, delta=1, reason=""),
            KarmaAction(user_id=222, delta=-1, reason=""),
        ]

    def test_no_match_plain_text(self) -> None:
        assert parse_karma_actions("hello world") == []

    def test_no_match_plain_name(self) -> None:
        assert parse_karma_actions("someone++") == []

    def test_no_match_invalid_operator(self) -> None:
        assert parse_karma_actions("<@123>+-") == []

    def test_whitespace_before_operator(self) -> None:
        result = parse_karma_actions("<@123> ++")
        assert result == [KarmaAction(user_id=123, delta=1, reason="")]

    def test_extra_plus_ignored(self) -> None:
        result = parse_karma_actions("<@123>+++")
        assert result == [KarmaAction(user_id=123, delta=1, reason="+")]

    def test_surrounded_by_text(self) -> None:
        result = parse_karma_actions("great job <@999>++ keep it up")
        assert result == [KarmaAction(user_id=999, delta=1, reason="keep it up")]

    def test_empty_string(self) -> None:
        assert parse_karma_actions("") == []

    def test_group_mention_increment(self) -> None:
        result = parse_karma_actions("<@111> <@222> <@333>++")
        assert result == [
            KarmaAction(user_id=111, delta=1, reason=""),
            KarmaAction(user_id=222, delta=1, reason=""),
            KarmaAction(user_id=333, delta=1, reason=""),
        ]

    def test_group_mention_decrement(self) -> None:
        result = parse_karma_actions("<@111> <@222>--")
        assert result == [
            KarmaAction(user_id=111, delta=-1, reason=""),
            KarmaAction(user_id=222, delta=-1, reason=""),
        ]

    def test_group_no_duplicate(self) -> None:
        result = parse_karma_actions("<@111> <@111>++")
        assert result == [KarmaAction(user_id=111, delta=1, reason="")]

    def test_group_with_nicknames(self) -> None:
        result = parse_karma_actions("<@!111> <@222>++")
        assert result == [
            KarmaAction(user_id=111, delta=1, reason=""),
            KarmaAction(user_id=222, delta=1, reason=""),
        ]

    def test_reason_captured(self) -> None:
        result = parse_karma_actions("<@123>++ for nice link")
        assert result == [KarmaAction(user_id=123, delta=1, reason="for nice link")]

    def test_reason_with_group(self) -> None:
        result = parse_karma_actions("<@111> <@222>++ great teamwork")
        assert result == [
            KarmaAction(user_id=111, delta=1, reason="great teamwork"),
            KarmaAction(user_id=222, delta=1, reason="great teamwork"),
        ]

    def test_no_reason(self) -> None:
        result = parse_karma_actions("<@123>++")
        assert result[0].reason == ""


class TestMilestones:
    def test_is_milestone_true(self) -> None:
        for m in MILESTONES:
            assert is_milestone(m) is True

    def test_is_milestone_false(self) -> None:
        for val in (0, 1, 3, 7, 11, 99, 101, 999):
            assert is_milestone(val) is False

    def test_get_milestone_tier_hit(self) -> None:
        assert get_milestone_tier(100) == 100

    def test_get_milestone_tier_miss(self) -> None:
        assert get_milestone_tier(42) is None
