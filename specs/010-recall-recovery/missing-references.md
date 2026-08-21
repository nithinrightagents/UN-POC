# Missing References Work List (T004)

**Generated**: 2026-08-21
**Source**: Set difference between `usa-sample-2026` cycle (25 questions, read from `data/usa_sample.db`) and `data/benchmark/reference_links_us.json` (13 entries).

## Already-covered IDs (7 of 25)

| Question ID | Already in reference_links_us.json |
|-------------|-------------------------------------|
| CP-030 | ✓ |
| IF-336 | ✓ |
| IF-337 | ✓ |
| IF-340 | ✓ |
| SP-043 | ✓ |
| SP-095 | ✓ |
| SP-108 | ✓ |

## Missing IDs requiring T005 entries (18 of 25)

| Question ID | Indicator | Sample State | Expected Answer | Reference URL (from GAP analysis) |
|-------------|-----------|--------------|-----------------|-----------------------------------|
| CP-015 | #015 | delivered | true | https://www.usa.gov/official-language-of-us |
| EGL-003 | #003 | delivered | true | https://www.usa.gov/search-gov |
| EGL-036b | #036b | delivered | true | https://www.usa.gov/libraries |
| EGL-321 | #321 | delivered | false | https://www.citizenscience.gov (correct answer; pipeline used outdated archive) |
| EP-141 | #141 | delivered | true | https://catalog.data.gov/dataset?organization=social-security-administration |
| EP-170 | #170 | delivered | true | https://catalog.data.gov |
| EP-304 | #304 | delivered | true | https://www.usaspending.gov |
| IF-011 | #011 | delivered | true | https://www.whitehouse.gov/administration/cabinet |
| IF-173 | #173 | delivered | true | https://www.justice.gov/olp/policy-initiatives |
| IF-338 | #338 | delivered | true | https://www.justice.gov/opcl (Privacy Act of 1974) |
| SP-048 | #048 | delivered | true | https://www.usa.gov/change-address |
| SP-062 | #062,#063 | delivered | false | (no national utility payment portal; municipal/private only) |
| SP-108a | #108a | delivered | false | (federal education mobile app retired 2022) |
| SP-124 | #124 | no_suggestion | true | https://www.usa.gov/jobs |
| SP-137b | #137b | delivered | true | https://www.ssa.gov (SMS notifications via opt-in) |
| SP-166 | #166 | no_suggestion | true | https://www.epa.gov |
| SP-166b | #166b | no_suggestion | true | https://www.enviroflash.info OR https://airnow.gov |
| TECH-022 | #022,#024 | delivered | true | https://www.login.gov |

## True Negatives requiring T006/T007 flags

| Question ID | Expected Answer | Reason |
|-------------|-----------------|--------|
| IF-336 | false | Already in reference; needs `no_valid_link: true` if not set |
| SP-062 (SP-062 entry) | false | No national utility payment portal — municipal/private only |
| SP-108a | false | Federal education mobile app retired 2022 |
