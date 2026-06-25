# Hunter.io Email Finder

Automated email discovery for Excel client lists using the Hunter.io API.

The script supports two input styles:

- Person + company rows: uses Hunter Email Finder to find that person's likely email.
- Company-only rows: uses Hunter Domain Search to find the best company email Hunter returns.

For the current `client list.xlsx`, the script detects:

- Company: `客户名称week1`
- Existing contact/email notes: `Email&联系方式`
- No person-name column yet, so rows without existing emails use company-level lookup.

## Features

- Reads `.xlsx` files.
- Detects English and Chinese column names.
- Reuses existing emails by default to avoid spending Hunter credits.
- Can optionally verify existing emails.
- Outputs all original columns plus email, score, phone, LinkedIn, domain, source, and status columns.
- Includes a dry-run mode to confirm columns before making API calls.

## Setup

Install dependencies:

```bash
pip install -r requirements.txt
```

Set your Hunter.io API key:

```powershell
$env:HUNTER_API_KEY = "your_api_key_here"
```

You can also pass it directly with `--api-key`.

## Usage

Check column detection without API calls:

```bash
python email_finder.py --dry-run
```

Process the default workbook:

```bash
python email_finder.py
```

Use custom files:

```bash
python email_finder.py --input "client list.xlsx" --output "client list_processed.xlsx"
```

Force Hunter lookup even when the row already has an email:

```bash
python email_finder.py --overwrite-existing
```

Verify existing emails with Hunter:

```bash
python email_finder.py --verify-existing
```

## Output Columns

The output workbook keeps the original columns and adds:

| Column | Description |
| --- | --- |
| `Email` | Email found or reused from the existing contact column |
| `Email_Score` | Hunter score/confidence |
| `Phone` | Phone number if Hunter returns one |
| `LinkedIn_URL` | LinkedIn URL/handle if available |
| `Found_Name` | Name returned by Hunter |
| `Found_Position` | Position returned by Hunter |
| `Company_Domain` | Domain returned by Hunter |
| `Verification_Status` | `valid`, `accept_all`, `unknown`, etc. |
| `Email_Source` | First public source URL Hunter returns |
| `Lookup_Status` | `found`, `found_personal`, `existing_email`, `not_found`, or API error status |
| `Lookup_Error` | Error detail, if Hunter returns one |

## Input Columns

Best results come from columns like:

- `Name` or `联系人`
- `Company` or `公司`
- `Position` or `职位`
- `Email` or `Email&联系方式`

Only a company column is required. If a person-name column exists, the script uses Hunter Email Finder. Without a person name, it uses Hunter Domain Search.

## Notes On Hunter Credits

By default, rows that already contain an email in the contact column are copied into `Email` and are not sent to Hunter. Use `--verify-existing` if you want Hunter to verify those existing emails, or `--overwrite-existing` if you want Hunter to look them up again.
