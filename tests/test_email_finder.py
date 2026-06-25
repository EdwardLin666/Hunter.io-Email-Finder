import unittest

from email_finder import HunterIOEmailFinder, detect_columns, extract_email


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self.payload = payload
        self.text = str(payload)

    def json(self):
        return self.payload


class EmailFinderTests(unittest.TestCase):
    def setUp(self):
        self.finder = HunterIOEmailFinder("test-api-key")

    def test_detects_current_chinese_workbook_columns(self):
        columns = [
            "客户名称week1",
            "类型",
            "领域",
            "核心标签（1句话）",
            "Email&联系方式",
            "优先级（5/5）",
        ]

        detected = detect_columns(columns)

        self.assertEqual(detected["company"], "客户名称week1")
        self.assertEqual(detected["contact"], "Email&联系方式")
        self.assertIsNone(detected["name"])

    def test_extracts_email_from_contact_notes(self):
        self.assertEqual(extract_email("网站投递 / sales@example.com"), "sales@example.com")
        self.assertEqual(extract_email("网站投递"), "")

    def test_parses_email_finder_v2_score_and_phone_number(self):
        response = FakeResponse(
            200,
            {
                "data": {
                    "email": "alexis@reddit.com",
                    "score": 97,
                    "first_name": "Alexis",
                    "last_name": "Ohanian",
                    "domain": "reddit.com",
                    "phone_number": "+1 555 0100",
                    "verification": {"status": "valid"},
                    "sources": [{"uri": "https://example.com/source"}],
                }
            },
        )

        result = self.finder._parse_email_finder_response(response)

        self.assertEqual(result["email"], "alexis@reddit.com")
        self.assertEqual(result["score"], 97)
        self.assertEqual(result["phone"], "+1 555 0100")
        self.assertEqual(result["found_name"], "Alexis Ohanian")
        self.assertEqual(result["verification_status"], "valid")

    def test_domain_search_picks_best_personal_email(self):
        response = FakeResponse(
            200,
            {
                "data": {
                    "domain": "intercom.com",
                    "emails": [
                        {"value": "info@intercom.com", "type": "generic", "confidence": 99},
                        {
                            "value": "ciaran@intercom.com",
                            "type": "personal",
                            "confidence": 92,
                            "first_name": "Ciaran",
                            "last_name": "Lee",
                            "verification": {"status": "valid"},
                        },
                    ],
                }
            },
        )

        result = self.finder._parse_domain_search_response(response)

        self.assertEqual(result["email"], "ciaran@intercom.com")
        self.assertEqual(result["score"], 92)
        self.assertEqual(result["status"], "found_personal")


if __name__ == "__main__":
    unittest.main()
