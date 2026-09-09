from unittest.mock import MagicMock, patch

from backend.sources.duckduckgo import DuckDuckGoAdapter
from backend.sources.registry import select_adapters
from backend.sources.sec_edgar import SecEdgarAdapter
from backend.sources.wikipedia import WikipediaAdapter


def test_duckduckgo_adapter_returns_normalized_results():
    with patch("backend.sources.duckduckgo.cache_get", return_value=None), \
         patch("backend.sources.duckduckgo.cache_set"), \
         patch("backend.sources.duckduckgo.DDGS") as mock_ddgs:
        mock_ddgs.return_value.text.return_value = [{"title": "T", "href": "https://x.com/a", "body": "b"}]
        results = DuckDuckGoAdapter().search("test query")
    assert results == [{"title": "T", "url": "https://x.com/a", "body": "b"}]


def test_duckduckgo_adapter_degrades_to_empty_list_on_failure():
    with patch("backend.sources.duckduckgo.cache_get", return_value=None), \
         patch("backend.sources.duckduckgo.DDGS") as mock_ddgs:
        mock_ddgs.return_value.text.side_effect = RuntimeError("rate limited")
        results = DuckDuckGoAdapter().search("test query")
    assert results == []


def test_wikipedia_adapter_parses_search_response():
    fake_response = MagicMock()
    fake_response.json.return_value = {
        "query": {"search": [{"title": "Acme Corp", "snippet": "Acme is a <b>company</b>."}]}
    }
    fake_response.raise_for_status = lambda: None
    with patch("backend.sources.wikipedia.cache_get", return_value=None), \
         patch("backend.sources.wikipedia.cache_set"), \
         patch("backend.sources.wikipedia.requests.get", return_value=fake_response):
        results = WikipediaAdapter().search("Acme Corp")
    assert results[0]["title"] == "Acme Corp"
    assert "<b>" not in results[0]["body"]
    assert results[0]["url"].endswith("Acme_Corp")


def test_wikipedia_adapter_degrades_on_request_exception():
    import requests
    with patch("backend.sources.wikipedia.cache_get", return_value=None), \
         patch("backend.sources.wikipedia.requests.get", side_effect=requests.RequestException("timeout")):
        results = WikipediaAdapter().search("Acme Corp")
    assert results == []


def test_sec_edgar_adapter_degrades_on_failure():
    import requests
    with patch("backend.sources.sec_edgar.cache_get", return_value=None), \
         patch("backend.sources.sec_edgar.requests.get", side_effect=requests.RequestException("down")):
        results = SecEdgarAdapter().search("Acme revenue")
    assert results == []


def test_registry_always_includes_duckduckgo():
    adapters = select_adapters("some random query")
    assert any(a.name == "duckduckgo" for a in adapters)


def test_registry_routes_filing_queries_to_sec_edgar():
    adapters = select_adapters("Acme Corp 10-K filing revenue")
    names = {a.name for a in adapters}
    assert "sec_edgar" in names


def test_registry_routes_overview_queries_to_wikipedia():
    adapters = select_adapters("Acme Corp overview and background")
    names = {a.name for a in adapters}
    assert "wikipedia" in names


def test_registry_does_not_over_route_unrelated_queries():
    adapters = select_adapters("Acme Corp risks criticism")
    names = {a.name for a in adapters}
    assert names == {"duckduckgo"}
