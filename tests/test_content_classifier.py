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


if __name__ == "__main__":
    unittest.main()
