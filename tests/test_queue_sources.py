"""Saved queue intake must validate inputs without fetching their contents."""

import importlib
from pathlib import Path
import plistlib
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def sources_module():
    assert importlib.util.find_spec("queue_sources") is not None, "Queue intake is not implemented"
    return importlib.import_module("queue_sources")


def test_url_normalization_preserves_meaningful_path_and_query():
    normalize = sources_module().normalize_url
    assert normalize(" HTTPS://Example.COM:443/Read/?b=2&a=1#part ") == "https://example.com/Read/?b=2&a=1"
    assert normalize("http://Example.COM:8080/Read") == "http://example.com:8080/Read"
    assert normalize("https://example.com/Read/") != normalize("https://example.com/Read")
    assert normalize("http://[::1]:80/path") == "http://[::1]/path"


def test_empty_query_delimiter_is_preserved():
    assert sources_module().normalize_url("https://example.com/read?#part") == "https://example.com/read?"


@pytest.mark.parametrize("value", [
    "javascript:alert(1)", "file:///tmp/a.html", "ftp://example.com/a", "https:///missing-host",
    "https://user:secret@example.com/", "https://@example.com/", "https://example.com:bad/",
    "https://example.com/a\nb", "https://example.com/\x00", "https://exam ple.com/",
    "https://example.com\\@other.example/", "https://example.com:70000/", "",
])
def test_invalid_urls_fail_clearly(value):
    with pytest.raises(ValueError, match="(?i)(url|http|website|address)"):
        sources_module().normalize_url(value)


def test_multiline_url_list_becomes_individual_queue_items():
    items = sources_module().sources_from_text("https://ONE.example/a#x\n\n  HTTP://two.example/b?x=1  \n")
    assert [item["source"] for item in items] == ["https://one.example/a", "http://two.example/b?x=1"]
    assert all(item["kind"] == "url" and item["group_name"] == "" and item["title"] for item in items)


def test_prose_with_a_link_remains_one_text_item():
    text = "Reading notes: keep these ideas\nVisit https://example.com later."
    assert sources_module().sources_from_text(text) == [{
        "kind": "text", "source": text, "title": "Reading notes: keep these ideas", "group_name": ""
    }]


def test_text_title_is_limited_and_blank_input_adds_nothing():
    module = sources_module()
    assert len(module.sources_from_text("A" * 150)[0]["title"]) <= 80
    assert module.sources_from_text(" \n ") == []


@pytest.mark.parametrize("value", ["ftp://example.com/a", "javascript:alert(1)", "https:example.com", "https://good.example\nfile:///tmp/private"])
def test_invalid_url_like_input_is_not_silently_saved_as_text(value):
    with pytest.raises(ValueError):
        sources_module().sources_from_text(value)


@pytest.mark.parametrize("fmt", [plistlib.FMT_XML, plistlib.FMT_BINARY])
def test_webloc_supports_xml_and_binary_property_lists(tmp_path, fmt):
    shortcut = tmp_path / "Article.webloc"
    shortcut.write_bytes(plistlib.dumps({"URL": "HTTPS://Example.com/read#section"}, fmt=fmt))
    assert sources_module().read_webloc(shortcut) == "https://example.com/read"


@pytest.mark.parametrize("contents", [b"not a property list", b'<?xml version="1.0"?><plist><dict>', plistlib.dumps({"Title": "Missing URL"}), plistlib.dumps({"URL": "file:///tmp/a"})])
def test_invalid_webloc_has_actionable_error(tmp_path, contents):
    shortcut = tmp_path / "Broken.webloc"
    shortcut.write_bytes(contents)
    with pytest.raises(ValueError, match="(?i)(webloc|url|http|website)"):
        sources_module().read_webloc(shortcut)
