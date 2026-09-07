import pytest
from shared.tools.linkresolution.sources.search import is_government_domain


@pytest.mark.parametrize(
    ("country_or_unit_id", "url", "expected"),
    [
        # F1 test cases that fail today due to alpha-2 vs ccTLD and city codes
        ("LON", "https://www.london.gov.uk/services", True),
        ("GB", "https://www.gov.uk/apply", True),
        ("MCR", "https://www.manchester.gov.uk/x", True),
        ("EDI", "https://www.edinburgh.gov.uk/x", True),
        # Existing working cases
        ("US", "https://www.usa.gov/x", True),
        ("DK", "https://www.borger.dk/x", True),
        ("BR", "https://www.gov.br/x", True),
        # Negative cases docstring defends
        ("US", "https://incometax.gov.in/iec/foportal/", False),
        ("DK", "https://www.usa.gov/x", False),
        ("GB", "https://incometax.gov.in/x", False),
        ("US", "https://www.google.com/search", False),
    ],
)
def test_is_government_domain(country_or_unit_id: str, url: str, expected: bool):
    """Test government domain gate against F1 table and negative test cases."""
    assert is_government_domain(url, country_or_unit_id) == expected
