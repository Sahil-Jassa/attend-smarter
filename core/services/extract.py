"""Vision extraction service for timetables and holiday lists using Anthropic API.
Extracts structured schedule data with strict validation, error flags, and manual fallback.
"""

import base64
import json
import mimetypes
import os
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple, Union


class ExtractionError(Exception):
    """Raised when extraction encounters an unrecoverable error."""
    pass


MAX_UPLOAD_SIZE = 5 * 1024 * 1024  # 5 MB
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".pdf"}


def strip_code_fences(text: str) -> str:
    """Remove markdown code fences (```json ... ```) from text."""
    text = text.strip()
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline + 1:]
        if text.endswith("```"):
            text = text[:-3]
    return text.strip()


def validate_upload_file(file_bytes: bytes, filename: str) -> Tuple[bool, Optional[str]]:
    """Validate file size (<= 5MB) and extension (jpg, png, pdf)."""
    if len(file_bytes) > MAX_UPLOAD_SIZE:
        return False, f"File size exceeds 5 MB limit ({len(file_bytes) / (1024*1024):.1f} MB uploaded)."

    _, ext = os.path.splitext(filename.lower())
    if ext not in ALLOWED_EXTENSIONS:
        return False, f"Unsupported file extension '{ext}'. Only JPG, PNG, and PDF are allowed."

    return True, None


def parse_indian_date(date_str: str) -> Optional[date]:
    """Parse DD/MM/YYYY date string. Also fallback to YYYY-MM-DD if model returns ISO format."""
    if not isinstance(date_str, str):
        return None
    date_str = date_str.strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue
    return None


def validate_timetable_data(data: Any, mode: str = "weekday") -> Dict[str, Any]:
    """Validate extracted timetable dictionary:
    - subjects non-empty name
    - slots periods >= 1
    - valid weekday or day_order
    Flags invalid items instead of crashing.
    """
    valid_subjects: List[Dict[str, Any]] = []
    errors: List[str] = []

    if not isinstance(data, dict) or "subjects" not in data or not isinstance(data["subjects"], list):
        return {
            "valid_subjects": [],
            "errors": ["Extracted data does not contain a valid 'subjects' list."],
        }

    weekday_name_map = {
        "monday": 0, "mon": 0,
        "tuesday": 1, "tue": 1,
        "wednesday": 2, "wed": 2,
        "thursday": 3, "thu": 3,
        "friday": 4, "fri": 4,
        "saturday": 5, "sat": 5,
        "sunday": 6, "sun": 6,
    }

    for idx, subj in enumerate(data["subjects"]):
        if not isinstance(subj, dict):
            errors.append(f"Subject #{idx + 1} is not a valid object.")
            continue

        name = str(subj.get("name", "")).strip()
        if not name:
            errors.append(f"Subject #{idx + 1} has an empty or missing name.")
            continue

        raw_slots = subj.get("slots", [])
        if not isinstance(raw_slots, list):
            errors.append(f"Subject '{name}' has invalid slots specification.")
            continue

        valid_slots: List[Dict[str, Any]] = []
        for s_idx, slot in enumerate(raw_slots):
            if not isinstance(slot, dict):
                errors.append(f"Subject '{name}' slot #{s_idx + 1} is not a valid object.")
                continue

            raw_p = slot.get("periods", 1)
            try:
                periods = int(raw_p)
                if periods < 1:
                    errors.append(f"Subject '{name}' slot #{s_idx + 1} periods must be >= 1 (got {raw_p}).")
                    continue
            except (ValueError, TypeError):
                errors.append(f"Subject '{name}' slot #{s_idx + 1} periods is not an integer ({raw_p}).")
                continue

            raw_day = slot.get("weekday_or_day_order")
            if raw_day is None:
                raw_day = slot.get("weekday") if slot.get("weekday") is not None else slot.get("day_order")

            if mode == "day_order":
                try:
                    day_val = int(raw_day)
                    if not (1 <= day_val <= 10):
                        errors.append(f"Subject '{name}' day order {day_val} is out of expected range (1-10).")
                        continue
                except (ValueError, TypeError):
                    errors.append(f"Subject '{name}' day order '{raw_day}' is not an integer.")
                    continue
            else:
                if isinstance(raw_day, str):
                    raw_day_clean = raw_day.strip().lower()
                    if raw_day_clean in weekday_name_map:
                        day_val = weekday_name_map[raw_day_clean]
                    else:
                        try:
                            day_val = int(raw_day_clean)
                        except ValueError:
                            errors.append(f"Subject '{name}' weekday '{raw_day}' could not be identified.")
                            continue
                else:
                    try:
                        day_val = int(raw_day)
                    except (ValueError, TypeError):
                        errors.append(f"Subject '{name}' weekday '{raw_day}' is not valid.")
                        continue

                if not (0 <= day_val <= 6):
                    errors.append(f"Subject '{name}' weekday {day_val} is out of range (0-6).")
                    continue

            valid_slots.append({
                "weekday_or_day_order": day_val,
                "periods": periods,
            })

        valid_subjects.append({
            "name": name,
            "slots": valid_slots,
        })

    return {
        "valid_subjects": valid_subjects,
        "errors": errors,
    }


def validate_holidays_data(
    data: Any,
    start_date: Optional[date] = None,
    last_working_day: Optional[date] = None,
) -> Dict[str, Any]:
    """Validate extracted holiday dictionary:
    - single dates or start/end date ranges
    - dates in DD/MM/YYYY
    - dates fall within start_date..last_working_day if provided
    Flags invalid items instead of crashing.
    """
    valid_holidays: List[Dict[str, Any]] = []
    errors: List[str] = []

    if not isinstance(data, dict) or "holidays" not in data or not isinstance(data["holidays"], list):
        return {
            "valid_holidays": [],
            "errors": ["Extracted data does not contain a valid 'holidays' list."],
        }

    for idx, item in enumerate(data["holidays"]):
        if not isinstance(item, dict):
            errors.append(f"Holiday #{idx + 1} is not a valid object.")
            continue

        label = str(item.get("label", "")).strip() or "Holiday"

        if "start" in item and "end" in item:
            d_start = parse_indian_date(item["start"])
            d_end = parse_indian_date(item["end"])
            if not d_start or not d_end:
                errors.append(f"Holiday '{label}' has invalid date format in range '{item.get('start')}' - '{item.get('end')}'. Use DD/MM/YYYY.")
                continue
            if d_start > d_end:
                errors.append(f"Holiday '{label}' start date ({d_start}) is after end date ({d_end}).")
                continue

            if start_date and last_working_day:
                if d_end < start_date or d_start > last_working_day:
                    errors.append(f"Holiday '{label}' ({d_start} to {d_end}) is outside semester range ({start_date} to {last_working_day}).")
                    continue

            valid_holidays.append({
                "start": d_start,
                "end": d_end,
                "label": label,
            })
        elif "date" in item:
            d = parse_indian_date(item["date"])
            if not d:
                errors.append(f"Holiday '{label}' has invalid date format '{item.get('date')}'. Use DD/MM/YYYY.")
                continue

            if start_date and last_working_day:
                if d < start_date or d > last_working_day:
                    errors.append(f"Holiday '{label}' on {d} is outside semester range ({start_date} to {last_working_day}).")
                    continue

            valid_holidays.append({
                "date": d,
                "label": label,
            })
        else:
            errors.append(f"Holiday #{idx + 1} ('{label}') missing 'date' or 'start'/'end' keys.")

    return {
        "valid_holidays": valid_holidays,
        "errors": errors,
    }


from dotenv import load_dotenv

load_dotenv()


def call_gemini_vision(
    image_bytes: bytes,
    mime_type: str,
    prompt: str,
    api_key: str,
    model: str,
) -> str:
    """Call Google Gemini vision API with image or PDF bytes."""
    import urllib.request
    import urllib.error

    base64_data = base64.b64encode(image_bytes).decode("utf-8")
    actual_mime = mime_type if mime_type in ("image/jpeg", "image/png", "image/webp", "application/pdf") else "image/jpeg"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "inline_data": {
                            "mime_type": actual_mime,
                            "data": base64_data,
                        }
                    },
                    {"text": prompt},
                ]
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json"
        }
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp_data = json.loads(resp.read().decode("utf-8"))
            candidates = resp_data.get("candidates", [])
            if not candidates:
                return ""
            parts = candidates[0].get("content", {}).get("parts", [])
            return "".join(part.get("text", "") for part in parts)
    except urllib.error.HTTPError as he:
        err_msg = ""
        try:
            err_data = json.loads(he.read().decode("utf-8"))
            err_msg = err_data.get("error", {}).get("message", "")
        except Exception:
            err_msg = he.reason

        if api_key and api_key in err_msg:
            err_msg = err_msg.replace(api_key, "[REDACTED]")

        if he.code in (401, 403) or (he.code == 400 and any(k in err_msg.lower() for k in ("key", "api_key", "credential"))):
            raise ExtractionError(f"bad key (HTTP {he.code}): {err_msg}")
        elif he.code == 404:
            raise ExtractionError(f"model error: model '{model}' not found (HTTP 404): {err_msg}")
        elif he.code == 429:
            raise ExtractionError(f"quota exceeded (HTTP 429): {err_msg}")
        else:
            raise ExtractionError(f"Gemini API error (HTTP {he.code}): {err_msg}")
    except urllib.error.URLError as ue:
        raise ExtractionError(f"network error: {ue.reason}")
    except Exception as exc:
        raise ExtractionError(f"Gemini API request failed: {type(exc).__name__}")


# Alias for backward compatibility if needed
call_anthropic_vision = call_gemini_vision


def extract_timetable_from_image(
    file_bytes: bytes,
    filename: str = "timetable.png",
    mode: str = "weekday",
    api_key: Optional[str] = None,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """Extract timetable schedule from image/PDF using Gemini vision."""
    api_key = api_key or os.environ.get("GEMINI_API_KEY")
    model = model or os.environ.get("GEMINI_MODEL")

    if not model or model.strip() == "PASTE_MODEL_HERE":
        model = "gemini-flash-lite-latest"

    if not api_key or api_key.strip() in ("", "PASTE_KEY_HERE"):
        return {
            "success": False,
            "error": "Gemini API key is missing. Please set GEMINI_API_KEY in your .env or enter your timetable manually.",
            "data": {"valid_subjects": [], "errors": []},
        }

    mime_type, _ = mimetypes.guess_type(filename)
    if not mime_type:
        mime_type = "image/png" if filename.lower().endswith(".png") else "image/jpeg"

    prompt = (
        "Extract the academic class timetable from this schedule image/document.\n"
        "Output ONLY a STRICT JSON object without any preamble or conversational text.\n"
        "Format schema:\n"
        "{\n"
        '  "subjects": [\n'
        '    {\n'
        '      "name": "Subject Name",\n'
        '      "slots": [\n'
        '        {\n'
        f'          "weekday_or_day_order": {"integer 0 for Monday through 6 for Sunday" if mode == "weekday" else "integer 1 to 5 for Day Order"},\n'
        '          "periods": 1 // integer count of periods (e.g. 2 or 3 for lab)\n'
        '        }\n'
        '      ]\n'
        '    }\n'
        '  ]\n'
        "}\n"
        "Ensure all subject names are non-empty strings and periods are integers >= 1."
    )

    try:
        raw_text = call_gemini_vision(file_bytes, mime_type, prompt, api_key, model)
        cleaned = strip_code_fences(raw_text)
        parsed_json = json.loads(cleaned)
        validated = validate_timetable_data(parsed_json, mode=mode)
        return {
            "success": True,
            "data": validated,
            "error": None,
        }
    except json.JSONDecodeError as jde:
        return {
            "success": False,
            "error": f"Failed to parse LLM vision output as valid JSON: {jde}. You can enter your timetable manually.",
            "data": {"valid_subjects": [], "errors": [str(jde)]},
        }
    except ExtractionError as ee:
        return {
            "success": False,
            "error": f"Timetable extraction failed ({ee}). You can enter your timetable manually.",
            "data": {"valid_subjects": [], "errors": [str(ee)]},
        }
    except Exception as exc:
        return {
            "success": False,
            "error": f"Timetable extraction failed: {exc}. You can enter your timetable manually.",
            "data": {"valid_subjects": [], "errors": [str(exc)]},
        }


def extract_holidays_from_image(
    file_bytes: bytes,
    filename: str = "holidays.png",
    start_date: Optional[date] = None,
    last_working_day: Optional[date] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """Extract academic holiday list from image/PDF using Gemini vision."""
    api_key = api_key or os.environ.get("GEMINI_API_KEY")
    model = model or os.environ.get("GEMINI_MODEL")

    if not model or model.strip() == "PASTE_MODEL_HERE":
        model = "gemini-flash-lite-latest"

    if not api_key or api_key.strip() in ("", "PASTE_KEY_HERE"):
        return {
            "success": False,
            "error": "Gemini API key is missing. Please set GEMINI_API_KEY in your .env or enter holidays manually.",
            "data": {"valid_holidays": [], "errors": []},
        }

    mime_type, _ = mimetypes.guess_type(filename)
    if not mime_type:
        mime_type = "image/png" if filename.lower().endswith(".png") else "image/jpeg"

    prompt = (
        "Extract the holiday list or academic calendar holidays from this image/document.\n"
        "Output ONLY a STRICT JSON object without any preamble or conversational text.\n"
        "Dates MUST be formatted as DD/MM/YYYY (Indian standard format).\n"
        "Format schema:\n"
        "{\n"
        '  "holidays": [\n'
        '    {\n'
        '      "date": "DD/MM/YYYY", // or use "start": "DD/MM/YYYY", "end": "DD/MM/YYYY" for ranges\n'
        '      "label": "Holiday or Event Name"\n'
        '    }\n'
        '  ]\n'
        "}\n"
    )

    try:
        raw_text = call_gemini_vision(file_bytes, mime_type, prompt, api_key, model)
        cleaned = strip_code_fences(raw_text)
        parsed_json = json.loads(cleaned)
        validated = validate_holidays_data(parsed_json, start_date=start_date, last_working_day=last_working_day)
        return {
            "success": True,
            "data": validated,
            "error": None,
        }
    except json.JSONDecodeError as jde:
        return {
            "success": False,
            "error": f"Failed to parse LLM vision output as valid JSON: {jde}. You can enter holidays manually.",
            "data": {"valid_holidays": [], "errors": [str(jde)]},
        }
    except ExtractionError as ee:
        return {
            "success": False,
            "error": f"Holiday extraction failed ({ee}). You can enter holidays manually.",
            "data": {"valid_holidays": [], "errors": [str(ee)]},
        }
    except Exception as exc:
        return {
            "success": False,
            "error": f"Holiday extraction failed: {exc}. You can enter holidays manually.",
            "data": {"valid_holidays": [], "errors": [str(exc)]},
        }

