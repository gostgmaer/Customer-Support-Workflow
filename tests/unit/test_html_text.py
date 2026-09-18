"""app.integrations.html_text.html_to_text - pure unit tests, no HTTP
(the Confluence storage-format stripper - spec: Phase 9.3)."""

from __future__ import annotations

from app.integrations.html_text import html_to_text


def test_strips_tags_and_keeps_text():
    assert html_to_text("<p>Hello <strong>world</strong>.</p>") == "Hello world."


def test_decodes_entities():
    assert html_to_text("<p>Fish &amp; chips &lt;tasty&gt;</p>") == "Fish & chips <tasty>"


def test_block_elements_produce_paragraph_breaks():
    result = html_to_text("<p>First paragraph.</p><p>Second paragraph.</p>")
    assert result == "First paragraph.\n\nSecond paragraph."


def test_list_items_are_separated():
    result = html_to_text("<ul><li>Item one</li><li>Item two</li></ul>")
    assert "Item one" in result
    assert "Item two" in result
    assert result.index("Item one") < result.index("Item two")


def test_br_produces_a_line_break_not_a_paragraph_break():
    result = html_to_text("<p>Line one<br/>Line two</p>")
    assert "Line one" in result and "Line two" in result


def test_malformed_unclosed_tags_do_not_raise():
    result = html_to_text("<p>Unclosed paragraph <strong>bold text")
    assert "Unclosed paragraph" in result
    assert "bold text" in result


def test_nested_tags_do_not_duplicate_text():
    result = html_to_text("<div><p>Nested <em>content</em> here.</p></div>")
    assert result.count("content") == 1


def test_whitespace_is_collapsed():
    result = html_to_text("<p>Too    many     spaces</p>")
    assert result == "Too many spaces"


def test_empty_input_returns_empty_string():
    assert html_to_text("") == ""
