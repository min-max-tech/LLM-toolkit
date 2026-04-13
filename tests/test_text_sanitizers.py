"""Test text_sanitizers — security boundary for LLM-generated workflow IDs."""
from __future__ import annotations

from dashboard.text_sanitizers import clean_gemma_special_tokens, sanitize_workflow_id


class TestCleanGemmaSpecialTokens:
    def test_no_special_tokens_unchanged(self):
        assert clean_gemma_special_tokens("generate_image") == "generate_image"

    def test_double_quote_token(self):
        assert clean_gemma_special_tokens('<|"|>hello<|"|>') == '"hello"'

    def test_single_quote_token(self):
        assert clean_gemma_special_tokens("<|'|>test<|'|>") == "'test'"

    def test_backtick_token(self):
        assert clean_gemma_special_tokens("<|`|>code<|`|>") == "`code`"

    def test_newline_token(self):
        assert clean_gemma_special_tokens("<|\\n|>") == "\n"

    def test_generic_single_char_token(self):
        assert clean_gemma_special_tokens("<|!|>") == "!"

    def test_early_exit_no_pipe(self):
        result = clean_gemma_special_tokens("plain text no pipes")
        assert result == "plain text no pipes"


class TestSanitizeWorkflowId:
    def test_none_returns_none(self):
        assert sanitize_workflow_id(None) is None

    def test_plain_id(self):
        assert sanitize_workflow_id("generate_image") == "generate_image"

    def test_strips_whitespace(self):
        assert sanitize_workflow_id("  generate_image  ") == "generate_image"

    def test_strips_surrounding_quotes(self):
        assert sanitize_workflow_id('"generate_image"') == "generate_image"
        assert sanitize_workflow_id("'generate_image'") == "generate_image"
        assert sanitize_workflow_id("`generate_image`") == "generate_image"

    def test_mismatched_quotes_not_stripped(self):
        assert sanitize_workflow_id("'generate_image\"") == "'generate_image\""

    def test_cleans_gemma_tokens_then_strips(self):
        assert sanitize_workflow_id('<|"|>generate_image<|"|>') == "generate_image"

    def test_empty_string_returns_none(self):
        assert sanitize_workflow_id("") is None
        assert sanitize_workflow_id("   ") is None

    def test_only_quotes_returns_none(self):
        # After stripping quotes and whitespace, nothing remains
        assert sanitize_workflow_id('""') is None

    def test_path_traversal_not_stripped(self):
        # sanitize_workflow_id only cleans tokens/quotes — path validation is done elsewhere
        result = sanitize_workflow_id("../../../etc/passwd")
        assert result == "../../../etc/passwd"
