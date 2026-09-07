import pytest
from shared.tools.linkresolution.sources.sitemap import clear_cache


@pytest.fixture(autouse=True)
def _reset_sitemap_cache():
    clear_cache()
    yield
    clear_cache()
