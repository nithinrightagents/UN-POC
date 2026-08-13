Reference fixtures for the three link-resolution sources (T089), documenting
the success / empty / unusable-candidate case each source can return.
`tests/integration/test_link_resolution.py` exercises the same three cases
per source through equivalent inline fixtures (an in-memory SQLite repo for
`prior_survey_kb`/`msq`, an `httpx.MockTransport` for `search`) rather than
loading these files directly, since the chain's DB-backed sources need a
live `Repository`, not a bare URL string. These JSON files exist as the
canonical, human-readable description of each case.
