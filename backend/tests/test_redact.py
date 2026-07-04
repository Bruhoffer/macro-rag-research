"""Tests for app.utils.redact — a regression here silently leaks PII."""

from app.utils.redact import (
    make_name_scrubber,
    redact_addresses,
    redact_phones,
    scrub_text,
    strip_copyright_lines,
    strip_header_lines,
    strip_links,
)


class TestRedactAddresses:
    def test_simple_address(self):
        assert redact_addresses("contact jane.doe@fund.com today") == "contact [redacted] today"

    def test_address_with_plus_and_subdomain(self):
        assert redact_addresses("x+tag@mail.example.co.uk") == "[redacted]"

    def test_multiple_addresses(self):
        out = redact_addresses("a@x.com wrote to b@y.org")
        assert "@" not in out.replace("[redacted]", "")

    def test_none_and_empty_passthrough(self):
        assert redact_addresses(None) is None
        assert redact_addresses("") == ""

    def test_no_address_unchanged(self):
        text = "US CPI rose 0.3% m/m in June"
        assert redact_addresses(text) == text


class TestStripHeaderLines:
    def test_from_line_removed(self):
        text = "From: Jane Doe <jane@fund.com>\nCPI came in hot."
        assert "Jane Doe" not in strip_header_lines(text)
        assert "CPI came in hot." in strip_header_lines(text)

    def test_quoted_forward_header_removed(self):
        text = "> From: Analyst <a@bank.com>\n> body text"
        out = strip_header_lines(text)
        assert "Analyst" not in out
        assert "body text" in out

    def test_all_header_keywords(self):
        for kw in ("From", "To", "Cc", "Bcc", "Sent", "Reply-To"):
            assert strip_header_lines(f"{kw}: someone\nkeep me") .strip() == "keep me"

    def test_prose_starting_with_from_kept(self):
        text = "From the CIO: markets look stretched"
        assert strip_header_lines(text) == text

    def test_sent_from_device_kept(self):
        text = "Sent from my iPhone"
        assert strip_header_lines(text) == text

    def test_case_insensitive(self):
        assert strip_header_lines("FROM: X\nkeep").strip() == "keep"


class TestStripLinks:
    def test_tracking_url_wrapper_removed(self):
        text = "Read Full Report <https://url.uk.m.mimecastprotect.com/s/G62OCX?domain=citivelocity.com>"
        assert strip_links(text) == "Read Full Report "

    def test_mailto_and_tel_wrappers_removed(self):
        text = "call <tel:+1-212-816-2991> or write <mailto:x@y.com?subject=RE:Monitor>"
        out = strip_links(text)
        assert "tel:" not in out and "mailto:" not in out

    def test_plain_angle_brackets_kept(self):
        text = "spread <10bp is tight"
        assert strip_links(text) == text

    def test_bare_url_kept(self):
        # only angle-wrapped links are dropped; inline prose URLs survive
        text = "see https://example.com/report for details"
        assert strip_links(text) == text


class TestRedactPhones:
    def test_international_number(self):
        assert redact_phones("desk: +1-212-816-2991 ext") == "desk: [redacted] ext"

    def test_spaces_and_parens(self):
        assert "+44" not in redact_phones("+44 (0)20 7986 4000")

    def test_prices_untouched(self):
        text = "target +1.5% and 2026-06-30 close 4,250"
        assert redact_phones(text) == text


class TestStripCopyrightLines:
    def test_citi_copyright_line_removed(self):
        text = (
            "Rate path chart\n"
            "© 2026 Citigroup Inc. No redistribution without Citigroup's written permission.\n"
            "Source: Citi Research"
        )
        out = strip_copyright_lines(text)
        assert "Citigroup Inc" not in out
        assert "Rate path chart" in out and "Source: Citi Research" in out

    def test_copyright_word_with_year_removed(self):
        assert strip_copyright_lines("Copyright 2026 Bank plc. All rights reserved.").strip() == ""

    def test_prose_mentioning_copyright_kept(self):
        text = "the copyright ruling weighed on media stocks"
        assert strip_copyright_lines(text) == text


class TestScrubText:
    def test_citi_style_footer(self):
        body = (
            "2026 Y/E Policy Rate Forecasts (Citi)\n"
            "[image] <https://url.uk.m.mimecastprotect.com/s/2eWoCY?domain=citivelocity.com>\n"
            "Nathan SheetsAC<https://url.uk.m.mimecastprotect.com/s/IOdrCN?domain=citivelocity.com>\n"
            "analyst@bank.com<mailto:analyst@bank.com?subject=RE:Monitor>\n"
            "+1-212-816-2991<tel:+1-212-816-2991>\n"
        )
        out = scrub_text(body)
        assert "mimecastprotect" not in out
        assert "mailto:" not in out and "tel:" not in out
        assert "analyst@bank.com" not in out
        assert "+1-212-816-2991" not in out
        assert "2026 Y/E Policy Rate Forecasts (Citi)" in out


    def test_forwarded_chain(self):
        body = (
            "FYI\n"
            "From: Jane Doe <jane@fund.com>\n"
            "Sent: Monday, June 1\n"
            "To: Macro AI <ai@fund.com>\n"
            "Subject line stays if not a header keyword\n"
            "JPM sees EUR/USD at 1.15 by year-end (contact: strategist@jpm.com)."
        )
        out = scrub_text(body)
        assert "Jane Doe" not in out
        assert "jane@fund.com" not in out
        assert "ai@fund.com" not in out
        assert "strategist@jpm.com" not in out
        assert "JPM sees EUR/USD at 1.15" in out

    def test_none_passthrough(self):
        assert scrub_text(None) is None


class TestMakeNameScrubber:
    def test_bounded_name_scrubbed(self):
        scrub = make_name_scrubber(["Jane Doe", "Jane", "Doe"])
        assert "Jane" not in scrub("Best regards, Jane Doe")

    def test_bounded_is_case_insensitive(self):
        scrub = make_name_scrubber(["Doe"])
        assert scrub("DOE said") == "[redacted] said"

    def test_bounded_does_not_match_inside_words(self):
        scrub = make_name_scrubber(["Alice"])
        assert scrub("a golden chalice") == "a golden chalice"

    def test_substring_literal_matches_inside_tokens(self):
        scrub = make_name_scrubber(["~fundco"])
        assert scrub("mailto:jane%40fundco.com") == "mailto:jane%40[redacted].com"
        assert scrub("logo_fundco_investments.png") == "logo_[redacted]_investments.png"

    def test_longer_literal_wins(self):
        scrub = make_name_scrubber(["Jane", "Jane Doe"])
        assert scrub("Jane Doe wrote") == "[redacted] wrote"

    def test_empty_list_is_identity(self):
        scrub = make_name_scrubber([])
        assert scrub("anything at all") == "anything at all"

    def test_none_passthrough(self):
        scrub = make_name_scrubber(["Jane"])
        assert scrub(None) is None
