# Curating and Managing Diagnostic Reference Links

This guide describes how to maintain reference link sets for the Link Resolution Diagnostics engine (`src/benchmark/diagnostics.py`).

## Reference Link Schema

Reference link sets are stored as JSON files (e.g. `data/benchmark/reference_links_us.json`).
Each entry in the `entries` array conforms to the following schema:

```json
{
  "question_id": "CP-030",
  "indicator_id": "#030",
  "country_id": "US",
  "expected_answer": true,
  "reference_url": "https://www.usaspending.gov/search",
  "no_valid_link": false,
  "accepted_alternatives": [
    "https://www.usaspending.gov/search/"
  ],
  "confidence": "authoritative",
  "verified_on": "2026-08-21",
  "origin": "un_egov_2024",
  "note": "Authoritative federal procurement results portal"
}
```

### Field Definitions

1. **`question_id`**: The target question/survey item ID (e.g. `CP-030` or `SP-095`).
2. **`indicator_id`**: The UN indicator ID (e.g. `#030`, `#095`).
3. **`country_id`**: The ISO-2 country code (e.g. `US`, `DK`).
4. **`expected_answer`**: Boolean (`true`/`false`) or null if not evaluated.
5. **`reference_url`**: Canonical URL serving the feature as defined by UN e-government assessment guidelines.
6. **`no_valid_link`**: Set to `true` when no valid national government page exists (e.g. driver's licenses issued only at state/subnational level in the US). When `true`, pipeline resolving to the portal homepage is treated as a valid pass (`match`).
7. **`accepted_alternatives`**: Array of valid alternate URLs that also satisfy the indicator.
8. **`confidence`**:
   - `authoritative`: Verified by an expert on a specific date against official government portals. Authoritative references form the **Headline Pass Rate**.
   - `provisional`: Tentative or unverified references (e.g. generic landing pages or indicators where jurisdiction is ambiguous). Provisional references are reported in distinct totals and never inflate headline pass rates.
9. **`verified_on`**: ISO-8601 date string (`YYYY-MM-DD`) when the reference was manually verified.
10. **`origin`**: Attribution source (e.g. `manual_curation`, `un_egov_2024`, `msq_submission`).
11. **`note`**: Context explaining why the link was selected or why it is marked provisional.

## Adding or Updating a Reference

1. Open `data/benchmark/reference_links_us.json` (or create a new benchmark fixture for a different country).
2. Ensure `verified_on` is updated to today's date.
3. Test that the reference is reachable and non-stale:
   ```bash
   python -m src.cli diagnose run --reference-set bm-reference-links-us --check-staleness --resolve-only
   ```
4. Check for regressions against earlier baseline sessions:
   ```bash
   python -m src.cli diagnose compare <baseline_session_id> <new_session_id> --fail-on-regression
   ```
