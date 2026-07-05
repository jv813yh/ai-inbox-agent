import unittest

from src.content_classifier import classify_youtube_item, folder_parts_for_youtube


class ContentClassifierTests(unittest.TestCase):
    def test_known_investment_channels_route_to_investovanie(self):
        item = {"channel": "Kapitalista", "title": "ETF portfolio"}

        classification = classify_youtube_item(item, email_text="")

        self.assertEqual(classification["domain"], "Investovanie")
        self.assertEqual(classification["channel_name"], "Kapitalista")
        self.assertEqual(classification["channel_slug"], "kapitalista")
        self.assertEqual(folder_parts_for_youtube(classification), ["YouTube", "Investovanie", "Kapitalista"])

    def test_known_dominik_kovarik_variants_route_to_investovanie(self):
        item = {"channel": "Dominik Kovařík", "title": "Akcie a portfolio"}

        classification = classify_youtube_item(item, email_text="")

        self.assertEqual(classification["domain"], "Investovanie")
        self.assertEqual(classification["channel_name"], "Dominik Kovarik")
        self.assertEqual(folder_parts_for_youtube(classification), ["YouTube", "Investovanie", "Dominik Kovarik"])

    def test_technology_keywords_route_to_technologie(self):
        item = {"channel": "Some Tech Channel", "title": "Python backend API agents on Azure"}

        classification = classify_youtube_item(item, email_text="LLM automation and cloud backend")

        self.assertEqual(classification["domain"], "Technologie")
        self.assertEqual(classification["channel_name"], "Some Tech Channel")
        self.assertEqual(folder_parts_for_youtube(classification), ["YouTube", "Technologie", "Some Tech Channel"])

    def test_specific_video_beats_mixed_email_context(self):
        item = {"channel": "Anthropic", "title": "Prompting 101 | Code w/ Claude"}

        classification = classify_youtube_item(item, email_text="akcie portfolio investovanie ETF")

        self.assertEqual(classification["domain"], "Technologie")
        self.assertEqual(classification["topic"], "AI Agents")
        self.assertEqual(classification["channel_name"], "Anthropic")
        self.assertEqual(folder_parts_for_youtube(classification), ["YouTube", "Technologie", "Anthropic"])

    def test_unknown_video_can_still_use_email_context_as_fallback(self):
        item = {"channel": "Unknown Channel", "title": "Daily update"}

        classification = classify_youtube_item(item, email_text="ETF portfolio akcie")

        self.assertEqual(classification["domain"], "Investovanie")
        self.assertEqual(classification["method"], "email_keyword_fallback")

    def test_short_ai_keyword_does_not_match_inside_email_word(self):
        from src.content_classifier import classify_plain_email_item

        classification = classify_plain_email_item({
            "subject": "Email update",
            "from_addr": "sender@example.com",
            "summary": "Email summary",
            "my_take": "Follow up later.",
        })

        self.assertEqual(classification["domain"], "Ostatne")

    def test_article_classifier_routes_agentic_ai_to_technologie(self):
        from src.content_classifier import classify_article_item

        classification = classify_article_item({
            "url": "https://www.kdnuggets.com/agentic-ai-frameworks",
            "title": "10 Agentic AI Frameworks",
            "summary": "Tools for LLM agents and automation.",
        })

        self.assertEqual(classification["domain"], "Technologie")

    def test_article_host_beats_mixed_email_context(self):
        from src.content_classifier import classify_article_item

        classification = classify_article_item({
            "url": "https://techcommunity.microsoft.com/blog/azuredevcommunityblog/the-future-of-agentic-ai-inside-microsoft-agent-framework-1-0/4510698",
            "title": "The Future of Agentic AI: Inside Microsoft Agent Framework 1.0",
            "summary": "Microsoft released an agent framework for Python and .NET.",
        }, email_text="akcie portfolio investovanie ETF trader")

        self.assertEqual(classification["domain"], "Technologie")
        self.assertEqual(classification["method"], "known_host_map")


if __name__ == "__main__":
    unittest.main()
