from datetime import date
from unittest.mock import patch, MagicMock
from django.test import TestCase

from core.services.extract import (
    strip_code_fences,
    validate_timetable_data,
    validate_holidays_data,
    extract_timetable_from_image,
    extract_holidays_from_image,
    ExtractionError,
    validate_upload_file,
)


class ExtractServiceTests(TestCase):
    def test_strip_code_fences(self):
        raw = "```json\n{\"subjects\": []}\n```"
        self.assertEqual(strip_code_fences(raw), '{"subjects": []}')

        raw2 = "```\n{\"holidays\": []}\n```"
        self.assertEqual(strip_code_fences(raw2), '{"holidays": []}')

        raw3 = "  {\"plain\": 123}  "
        self.assertEqual(strip_code_fences(raw3), '{"plain": 123}')

    def test_validate_timetable_data_valid(self):
        data = {
            "subjects": [
                {
                    "name": "Maths",
                    "slots": [
                        {"weekday_or_day_order": 0, "periods": 1},
                        {"weekday_or_day_order": 2, "periods": 2},
                    ],
                }
            ]
        }
        res = validate_timetable_data(data, mode="weekday")
        self.assertEqual(len(res["valid_subjects"]), 1)
        self.assertEqual(len(res["errors"]), 0)
        self.assertEqual(res["valid_subjects"][0]["name"], "Maths")
        self.assertEqual(len(res["valid_subjects"][0]["slots"]), 2)

    def test_validate_timetable_empty_name(self):
        data = {
            "subjects": [
                {"name": "", "slots": [{"weekday_or_day_order": 0, "periods": 1}]},
                {"name": "   ", "slots": [{"weekday_or_day_order": 1, "periods": 1}]},
                {"name": "Physics", "slots": [{"weekday_or_day_order": 2, "periods": 1}]},
            ]
        }
        res = validate_timetable_data(data, mode="weekday")
        self.assertEqual(len(res["valid_subjects"]), 1)
        self.assertEqual(res["valid_subjects"][0]["name"], "Physics")
        self.assertEqual(len(res["errors"]), 2)
        self.assertIn("empty", res["errors"][0].lower())

    def test_validate_timetable_invalid_periods(self):
        data = {
            "subjects": [
                {
                    "name": "Chemistry",
                    "slots": [
                        {"weekday_or_day_order": 0, "periods": 0},   # Invalid: < 1
                        {"weekday_or_day_order": 1, "periods": -2},  # Invalid: < 1
                        {"weekday_or_day_order": 2, "periods": "abc"},  # Invalid: not int
                        {"weekday_or_day_order": 3, "periods": 2},   # Valid
                    ],
                }
            ]
        }
        res = validate_timetable_data(data, mode="weekday")
        self.assertEqual(len(res["valid_subjects"]), 1)
        # Only the valid slot should remain
        self.assertEqual(len(res["valid_subjects"][0]["slots"]), 1)
        self.assertEqual(res["valid_subjects"][0]["slots"][0]["periods"], 2)
        self.assertGreaterEqual(len(res["errors"]), 3)

    def test_validate_holidays_valid(self):
        start = date(2026, 8, 1)
        end = date(2026, 12, 31)
        data = {
            "holidays": [
                {"date": "15/08/2026", "label": "Independence Day"},
                {"start": "02/10/2026", "end": "03/10/2026", "label": "Gandhi Jayanti Break"},
            ]
        }
        res = validate_holidays_data(data, start_date=start, last_working_day=end)
        self.assertEqual(len(res["valid_holidays"]), 2)
        self.assertEqual(len(res["errors"]), 0)
        self.assertEqual(res["valid_holidays"][0]["date"], date(2026, 8, 15))
        self.assertEqual(res["valid_holidays"][1]["start"], date(2026, 10, 2))
        self.assertEqual(res["valid_holidays"][1]["end"], date(2026, 10, 3))

    def test_validate_holidays_invalid_dates(self):
        start = date(2026, 8, 1)
        end = date(2026, 12, 31)
        data = {
            "holidays": [
                {"date": "99/99/2026", "label": "Invalid Date"},
                {"date": "not-a-date", "label": "Nonsense"},
            ]
        }
        res = validate_holidays_data(data, start_date=start, last_working_day=end)
        self.assertEqual(len(res["valid_holidays"]), 0)
        self.assertEqual(len(res["errors"]), 2)

    def test_validate_holidays_out_of_range(self):
        start = date(2026, 8, 1)
        end = date(2026, 11, 30)
        data = {
            "holidays": [
                {"date": "15/07/2026", "label": "Too Early"},
                {"date": "25/12/2026", "label": "Too Late"},
                {"date": "15/08/2026", "label": "In Range"},
            ]
        }
        res = validate_holidays_data(data, start_date=start, last_working_day=end)
        self.assertEqual(len(res["valid_holidays"]), 1)
        self.assertEqual(res["valid_holidays"][0]["label"], "In Range")
        self.assertEqual(len(res["errors"]), 2)

    @patch("core.services.extract.call_gemini_vision")
    def test_mocked_api_valid_timetable(self, mock_vision):
        mock_vision.return_value = '```json\n{"subjects": [{"name": "AI", "slots": [{"weekday_or_day_order": 1, "periods": 1}]}]}\n```'
        result = extract_timetable_from_image(b"fake_image_bytes", filename="timetable.png", api_key="test-key")
        self.assertTrue(result["success"])
        self.assertEqual(len(result["data"]["valid_subjects"]), 1)
        self.assertEqual(result["data"]["valid_subjects"][0]["name"], "AI")

    @patch("core.services.extract.call_gemini_vision")
    def test_mocked_api_malformed_json(self, mock_vision):
        mock_vision.return_value = "Sorry, here is the timetable: {this is not json}"
        result = extract_timetable_from_image(b"fake_image_bytes", filename="timetable.png", api_key="test-key")
        self.assertFalse(result["success"])
        self.assertIn("JSON", result["error"])

    def test_missing_api_key_friendly_fallback(self):
        with patch.dict("os.environ", {}, clear=True):
            result = extract_timetable_from_image(b"fake_image_bytes", filename="timetable.png", api_key=None)
            self.assertFalse(result["success"])
            self.assertIn("API key is missing", result["error"])

        with patch.dict("os.environ", {"GEMINI_API_KEY": "PASTE_KEY_HERE"}, clear=True):
            result2 = extract_timetable_from_image(b"fake_image_bytes", filename="timetable.png", api_key=None)
            self.assertFalse(result2["success"])
            self.assertIn("API key is missing", result2["error"])

    @patch("core.services.extract.call_gemini_vision")
    def test_api_specific_error_types(self, mock_vision):
        from core.services.extract import ExtractionError

        # Bad key
        mock_vision.side_effect = ExtractionError("bad key (HTTP 400): API key not valid")
        res1 = extract_timetable_from_image(b"fake", filename="timetable.png", api_key="test-key")
        self.assertFalse(res1["success"])
        self.assertIn("bad key", res1["error"])

        # Model error
        mock_vision.side_effect = ExtractionError("model error: model 'foo' not found (HTTP 404): Not found")
        res2 = extract_timetable_from_image(b"fake", filename="timetable.png", api_key="test-key")
        self.assertFalse(res2["success"])
        self.assertIn("model error", res2["error"])

        # Quota
        mock_vision.side_effect = ExtractionError("quota exceeded (HTTP 429): Rate limit")
        res3 = extract_timetable_from_image(b"fake", filename="timetable.png", api_key="test-key")
        self.assertFalse(res3["success"])
        self.assertIn("quota exceeded", res3["error"])

    def test_upload_limits(self):
        # > 5 MB
        large_bytes = b"0" * (5 * 1024 * 1024 + 1)
        valid, err = validate_upload_file(large_bytes, "timetable.png")
        self.assertFalse(valid)
        self.assertIn("5 MB", err)

        # Invalid extension
        valid, err = validate_upload_file(b"content", "timetable.exe")
        self.assertFalse(valid)
        self.assertIn("extension", err.lower())

        # Valid extension and size
        valid, err = validate_upload_file(b"content", "timetable.jpg")
        self.assertTrue(valid)
        self.assertIsNone(err)
