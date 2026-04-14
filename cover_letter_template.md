# Cover letter template (DOCX pipeline)

The agent writes **`output/<slug>/cover_letter.json`**. The build step runs `python build_cover_letters.py`, which creates **`cover_letter.docx`** in the same folder.

## Letterhead

Name, address, phone, and links are fixed in `build_cover_letters.py` (constants at the top). Edit that file to change them.

## JSON schema

Write **valid UTF-8 JSON** only (no comments, no trailing commas). All string values use normal JSON escaping (`\"`, `\\`, newlines as `\n` if needed).

| Field | Required | Description |
|-------|----------|-------------|
| `date` | yes | e.g. `"April 13, 2026"` |
| `hiring_manager` | no | Defaults to `"Hiring Manager"` |
| `company` | yes | Company name |
| `location` | yes | City, state or full address line |
| `salutation` | no | Defaults to `"Dear Hiring Manager,"` |
| `opening` | yes | First body paragraph |
| `experience` | yes | Second body paragraph |
| `closing` | yes | Third body paragraph |

## Example

```json
{
  "date": "April 13, 2026",
  "hiring_manager": "Hiring Manager",
  "company": "Example Corp",
  "location": "San Francisco, CA",
  "salutation": "Dear Hiring Manager,",
  "opening": "The opening paragraph text...",
  "experience": "The evidence paragraph text...",
  "closing": "The closing paragraph text..."
}
```
