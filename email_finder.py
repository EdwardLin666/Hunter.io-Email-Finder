"""
Hunter.io Email Finder - automated email discovery for Excel client lists.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional, Sequence
from urllib.parse import urlparse

import pandas as pd
import requests


EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)


class HunterIOEmailFinder:
    """Find person or company email addresses with Hunter.io API v2."""

    def __init__(self, api_key: str, rate_limit_delay: float = 0.2, timeout: int = 30):
        self.base_url = "https://api.hunter.io/v2"
        self.rate_limit_delay = rate_limit_delay
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "EmailFinder/1.0",
                "X-API-KEY": api_key,
            }
        )

    def find_person_email(self, name: str, company: str, position: str = "") -> Dict[str, Any]:
        """Use Hunter Email Finder for rows that include a person's name."""
        name = clean_cell(name)
        company = clean_cell(company)
        position = clean_cell(position)

        if not name or not company:
            return self._empty_result("missing_name_or_company")

        params: Dict[str, Any] = {"full_name": name, "max_duration": 10}
        if self._looks_like_domain(company):
            params["domain"] = self._normalize_domain(company)
        else:
            params["company"] = company

        response = self._get("email-finder", params)
        result = self._parse_email_finder_response(response)

        if result["status"] == "not_found":
            fallback = self.find_company_email(company, job_title=position)
            if fallback.get("email"):
                fallback["status"] = "found_by_company_search"
                return fallback

        return result

    def find_company_email(self, company: str, job_title: str = "") -> Dict[str, Any]:
        """Use Hunter Domain Search for company-only rows."""
        company = clean_cell(company)
        job_title = clean_cell(job_title)

        if not company:
            return self._empty_result("missing_company")

        params: Dict[str, Any] = {"limit": 10}
        if self._looks_like_domain(company):
            params["domain"] = self._normalize_domain(company)
        else:
            params["company"] = company

        if job_title:
            params["job_titles"] = job_title

        response = self._get("domain-search", params)
        return self._parse_domain_search_response(response)

    def verify_email(self, email: str) -> Dict[str, Any]:
        email = clean_cell(email)
        if not email:
            return self._empty_result("missing_email")

        response = self._get("email-verifier", {"email": email})
        return self._parse_verifier_response(response)

    def _get(self, endpoint: str, params: Dict[str, Any]) -> requests.Response:
        response = self.session.get(
            f"{self.base_url}/{endpoint}",
            params={key: value for key, value in params.items() if value not in ("", None)},
            timeout=self.timeout,
        )
        time.sleep(self.rate_limit_delay)
        return response

    def _parse_email_finder_response(self, response: requests.Response) -> Dict[str, Any]:
        data = self._json(response)
        if response.status_code != 200:
            return self._error_result(response.status_code, data)

        item = data.get("data") or {}
        if not item.get("email"):
            return self._empty_result("not_found")

        verification = item.get("verification") or {}
        return {
            "email": item.get("email"),
            "score": item.get("score", 0),
            "phone": item.get("phone_number"),
            "linkedin_url": item.get("linkedin_url"),
            "found_name": join_name(item.get("first_name"), item.get("last_name")),
            "found_position": item.get("position"),
            "company_domain": item.get("domain"),
            "verification_status": verification.get("status"),
            "source": first_source_url(item.get("sources")),
            "status": "found",
        }

    def _parse_domain_search_response(self, response: requests.Response) -> Dict[str, Any]:
        data = self._json(response)
        if response.status_code != 200:
            return self._error_result(response.status_code, data)

        domain_data = data.get("data") or {}
        emails = domain_data.get("emails") or []
        best = self._best_domain_email(emails)

        if not best:
            return {
                **self._empty_result("not_found"),
                "company_domain": domain_data.get("domain"),
            }

        verification = best.get("verification") or {}
        return {
            "email": best.get("value"),
            "score": best.get("confidence", 0),
            "phone": best.get("phone_number"),
            "linkedin_url": best.get("linkedin"),
            "found_name": join_name(best.get("first_name"), best.get("last_name")),
            "found_position": best.get("position") or best.get("position_raw"),
            "company_domain": domain_data.get("domain"),
            "verification_status": verification.get("status"),
            "source": first_source_url(best.get("sources")),
            "status": f"found_{best.get('type', 'email')}",
        }

    def _parse_verifier_response(self, response: requests.Response) -> Dict[str, Any]:
        data = self._json(response)
        if response.status_code != 200:
            return self._error_result(response.status_code, data)

        item = data.get("data") or {}
        return {
            **self._empty_result("existing_email"),
            "email": item.get("email"),
            "score": item.get("score", 0),
            "verification_status": item.get("status"),
            "source": first_source_url(item.get("sources")),
        }

    def _best_domain_email(self, emails: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not emails:
            return None

        def rank(item: Dict[str, Any]) -> tuple[int, int, int]:
            is_personal = 1 if item.get("type") == "personal" else 0
            is_valid = 1 if (item.get("verification") or {}).get("status") == "valid" else 0
            confidence = int(item.get("confidence") or 0)
            return (is_personal, is_valid, confidence)

        return sorted(emails, key=rank, reverse=True)[0]

    def _error_result(self, status_code: int, data: Dict[str, Any]) -> Dict[str, Any]:
        details = self._error_details(data)
        status = f"api_error_{status_code}"
        if status_code == 401:
            status = "invalid_api_key"
        elif status_code == 403:
            status = "rate_limited"
        elif status_code == 429:
            status = "usage_limit_reached"
        elif status_code == 451:
            status = "privacy_restricted"

        return {
            **self._empty_result(status),
            "error": details or status,
        }

    def _empty_result(self, status: str) -> Dict[str, Any]:
        return {
            "email": "",
            "score": 0,
            "phone": "",
            "linkedin_url": "",
            "found_name": "",
            "found_position": "",
            "company_domain": "",
            "verification_status": "",
            "source": "",
            "status": status,
            "error": "",
        }

    def _json(self, response: requests.Response) -> Dict[str, Any]:
        try:
            return response.json()
        except ValueError:
            return {"errors": [{"details": response.text[:200]}]}

    def _error_details(self, data: Dict[str, Any]) -> str:
        errors = data.get("errors")
        if isinstance(errors, list):
            return "; ".join(str(item.get("details") or item) for item in errors)
        if errors:
            return str(errors)
        return ""

    def _looks_like_domain(self, value: str) -> bool:
        value = self._normalize_domain(value)
        return "." in value and " " not in value and not value.startswith(".")

    def _normalize_domain(self, value: str) -> str:
        value = clean_cell(value).lower()
        if value.startswith(("http://", "https://")):
            value = urlparse(value).hostname or value
        if "@" in value:
            value = value.split("@", 1)[1]
        if value.startswith("www."):
            value = value[4:]
        return value.strip().strip("/")


def process_file(
    finder: Optional[HunterIOEmailFinder],
    input_file: str,
    output_file: Optional[str] = None,
    *,
    overwrite_existing: bool = False,
    verify_existing: bool = False,
    dry_run: bool = False,
) -> str:
    if output_file is None:
        base, _ = os.path.splitext(input_file)
        output_file = f"{base}_processed.xlsx"

    print(f"Reading file: {input_file}")
    try:
        df = pd.read_excel(input_file)
    except Exception as exc:
        raise SystemExit(f"Error reading file: {exc}") from exc

    if df.empty:
        raise SystemExit("No data found in the input file.")

    columns = detect_columns(df.columns)
    if not columns["contact"]:
        columns["contact"] = infer_contact_column(df)
    if not columns["company"]:
        raise SystemExit(f"Error: could not detect a company column. Columns: {list(df.columns)}")

    print(f"Found {len(df)} records to process")
    print(f"Detected columns: {columns}")

    if dry_run:
        print("Dry run only. No Hunter.io API calls were made.")
        return output_file

    if finder is None:
        raise SystemExit("Hunter.io API key is required unless --dry-run is used.")

    ensure_output_columns(df)

    for idx, row in df.iterrows():
        company = clean_cell(row.get(columns["company"], ""))
        name = clean_cell(row.get(columns["name"], "")) if columns["name"] else ""
        position = clean_cell(row.get(columns["position"], "")) if columns["position"] else ""
        existing_email = extract_email(row.get(columns["contact"], "")) if columns["contact"] else ""

        label = name or company or f"row {idx + 1}"
        print(f"Processing {idx + 1}/{len(df)}: {label}", end=" ... ", flush=True)

        if existing_email and not overwrite_existing:
            result = finder.verify_email(existing_email) if verify_existing else finder._empty_result("existing_email")
            result["email"] = existing_email
        elif is_section_or_header_row(company):
            result = finder._empty_result("skipped_section_header")
        elif name:
            result = finder.find_person_email(name, company, position)
        else:
            result = finder.find_company_email(company, position)

        write_result(df, idx, result)
        print(f"{'OK' if result.get('email') else 'MISS'} {result.get('status', 'unknown')}")

    print(f"\nSaving results to: {output_file}")
    df.to_excel(output_file, index=False, engine="openpyxl")
    print_summary(df, output_file)
    return output_file


def detect_columns(columns: Sequence[str]) -> Dict[str, Optional[str]]:
    normalized = {normalize_header(column): column for column in columns}
    detected = {
        "name": first_present(
            normalized,
            "name",
            "fullname",
            "contactname",
            "person",
            "leadname",
            "联系人",
            "姓名",
            "客户姓名",
            "人名",
        ),
        "company": first_present(
            normalized,
            "company",
            "companyname",
            "organization",
            "account",
            "website",
            "domain",
            "客户名称week1",
            "客户名称",
            "公司",
            "公司名称",
            "企业名称",
        ),
        "position": first_present(
            normalized,
            "position",
            "jobtitle",
            "title",
            "role",
            "职位",
            "职务",
            "岗位",
        ),
        "contact": first_present(
            normalized,
            "email",
            "contact",
            "email联系方式",
            "emailand联系方式",
            "邮箱",
            "联系方式",
            "Email&联系方式",
        ),
    }

    if not detected["company"]:
        detected["company"] = find_matching_header(
            columns,
            lambda header: header.startswith("\u5ba2\u6237\u540d\u79f0"),
        )

    if not detected["contact"]:
        detected["contact"] = find_matching_header(
            columns,
            lambda header: "\u8054\u7cfb\u65b9\u5f0f" in header or "\u90ae\u7bb1" in header,
        )

    return detected


def find_matching_header(columns: Sequence[str], predicate: Any) -> Optional[str]:
    for column in columns:
        header = normalize_header(column)
        if predicate(header):
            return column
    return None


def infer_contact_column(df: pd.DataFrame) -> Optional[str]:
    best_column = None
    best_score = 0
    for column in df.columns:
        sample = df[column].dropna().astype(str).head(25)
        email_count = sum(1 for value in sample if extract_email(value))
        contact_note_count = sum(1 for value in sample if "\u7f51\u7ad9" in value or "\u6295\u9012" in value)
        score = email_count * 2 + contact_note_count
        if score > best_score:
            best_column = column
            best_score = score
    return best_column if best_score else None


def ensure_output_columns(df: pd.DataFrame) -> None:
    defaults = {
        "Email": "",
        "Email_Score": 0,
        "Phone": "",
        "LinkedIn_URL": "",
        "Found_Name": "",
        "Found_Position": "",
        "Company_Domain": "",
        "Verification_Status": "",
        "Email_Source": "",
        "Lookup_Status": "",
        "Lookup_Error": "",
    }
    for column, default in defaults.items():
        if column not in df.columns:
            df[column] = default


def write_result(df: pd.DataFrame, idx: int, result: Dict[str, Any]) -> None:
    df.at[idx, "Email"] = result.get("email") or ""
    df.at[idx, "Email_Score"] = result.get("score") or 0
    df.at[idx, "Phone"] = result.get("phone") or ""
    df.at[idx, "LinkedIn_URL"] = result.get("linkedin_url") or ""
    df.at[idx, "Found_Name"] = result.get("found_name") or ""
    df.at[idx, "Found_Position"] = result.get("found_position") or ""
    df.at[idx, "Company_Domain"] = result.get("company_domain") or ""
    df.at[idx, "Verification_Status"] = result.get("verification_status") or ""
    df.at[idx, "Email_Source"] = result.get("source") or ""
    df.at[idx, "Lookup_Status"] = result.get("status") or ""
    df.at[idx, "Lookup_Error"] = result.get("error") or ""


def print_summary(df: pd.DataFrame, output_file: str) -> None:
    found_count = df[df["Email"].notna() & (df["Email"] != "")].shape[0]
    print("\n" + "=" * 50)
    print("SUMMARY:")
    print(f"  Total records: {len(df)}")
    print(f"  Emails found: {found_count}")
    print(f"  Success rate: {(found_count / len(df) * 100):.1f}%")
    print(f"  Output file: {output_file}")
    print("=" * 50)


def clean_cell(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def extract_email(value: Any) -> str:
    match = EMAIL_RE.search(clean_cell(value))
    return match.group(0) if match else ""


def is_section_or_header_row(company: str) -> bool:
    value = clean_cell(company).lower()
    return bool(re.fullmatch(r"week\s*\d+\s*.*", value)) or value in {"type", "company", "field"}


def normalize_header(value: Any) -> str:
    return re.sub(r"[\s_&/()（）【】\[\]\-]+", "", str(value).strip().lower())


def first_present(columns: Dict[str, str], *candidates: str) -> Optional[str]:
    for candidate in candidates:
        exact = normalize_header(candidate)
        if exact in columns:
            return columns[exact]
    return None


def join_name(first_name: Any, last_name: Any) -> str:
    return " ".join(part for part in [clean_cell(first_name), clean_cell(last_name)] if part)


def first_source_url(sources: Any) -> str:
    if isinstance(sources, list) and sources:
        return clean_cell(sources[0].get("uri"))
    return ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Find emails in an Excel client list with Hunter.io")
    parser.add_argument("--input", "-i", default="client list.xlsx", help="Path to input Excel file")
    parser.add_argument("--output", "-o", default=None, help="Path to output Excel file")
    parser.add_argument("--api-key", "-k", default=None, help="Hunter.io API key")
    parser.add_argument("--delay", "-d", type=float, default=0.2, help="Delay between API requests in seconds")
    parser.add_argument("--overwrite-existing", action="store_true", help="Look up rows even when an email already exists")
    parser.add_argument("--verify-existing", action="store_true", help="Verify existing emails with Hunter.io")
    parser.add_argument("--dry-run", action="store_true", help="Read the file and detect columns without API calls")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_file = Path(args.input)
    if not input_file.exists():
        raise SystemExit(f"Error: Input file not found: {input_file}")

    api_key = args.api_key or os.getenv("HUNTER_API_KEY")
    finder = None
    if not args.dry_run:
        if not api_key:
            print("Hunter.io API key not found in HUNTER_API_KEY.")
            api_key = input("Please enter your Hunter.io API key: ").strip()
        if not api_key:
            raise SystemExit("Error: API key is required")
        finder = HunterIOEmailFinder(api_key, rate_limit_delay=args.delay)

    process_file(
        finder,
        str(input_file),
        args.output,
        overwrite_existing=args.overwrite_existing,
        verify_existing=args.verify_existing,
        dry_run=args.dry_run,
    )
    print("\nDone. Check the output file for results.")


if __name__ == "__main__":
    main()
