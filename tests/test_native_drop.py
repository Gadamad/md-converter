"""Exercise native pasteboard payloads without launching a window."""

from pathlib import Path
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import native_drop
from AppKit import NSPasteboardTypeFileURL, NSPasteboardTypeString, NSPasteboardTypeURL


class PasteboardItem:
    def __init__(self, values):
        self.values = values

    def stringForType_(self, kind):
        return self.values.get(kind)


class Pasteboard(PasteboardItem):
    def __init__(self, items=(), values=None, files=None):
        super().__init__(values or {})
        self.items = [PasteboardItem(item) for item in items]
        self.files = files

    def pasteboardItems(self):
        return self.items

    def propertyListForType_(self, kind):
        return self.files


def test_browser_drop_uses_all_url_items_instead_of_the_dragged_title():
    board = Pasteboard([
        {NSPasteboardTypeURL: "https://example.com/one", NSPasteboardTypeString: "Article one"},
        {NSPasteboardTypeURL: "https://example.com/two"},
    ])
    assert hasattr(native_drop, "_extract_links"), "Browser link extraction is not implemented"
    assert native_drop._extract_links(board) == {"urls": ["https://example.com/one", "https://example.com/two"]}


def test_plain_text_drop_and_board_level_url_are_supported():
    assert hasattr(native_drop, "_extract_links"), "Browser link extraction is not implemented"
    assert native_drop._extract_links(Pasteboard(values={NSPasteboardTypeURL: "https://example.com"})) == {"urls": ["https://example.com"]}
    assert native_drop._extract_links(Pasteboard([{NSPasteboardTypeString: "https://one.example\nhttps://two.example"}])) == {"text": "https://one.example\nhttps://two.example"}


def test_file_drop_keeps_priority_over_its_url_representation():
    assert hasattr(native_drop, "_dispatch_drop"), "Native drop dispatch is not implemented"
    board = Pasteboard([{NSPasteboardTypeFileURL: "file:///tmp/Article.webloc", NSPasteboardTypeURL: "https://example.com"}])
    received = []
    event = threading.Event()
    def file_callback(paths):
        received.append(("files", paths))
        event.set()
    assert native_drop._dispatch_drop(board, file_callback, lambda data: received.append(("links", data)))
    assert event.wait(1)
    assert received == [("files", ["/tmp/Article.webloc"])]


def test_link_drop_is_consumed_without_allowing_webview_navigation():
    assert hasattr(native_drop, "_dispatch_drop"), "Native drop dispatch is not implemented"
    received = []
    event = threading.Event()
    def callback(payload):
        received.append(payload)
        event.set()
    assert native_drop._dispatch_drop(Pasteboard([{NSPasteboardTypeURL: "https://example.com"}]), None, callback)
    assert event.wait(1)
    assert received == [{"urls": ["https://example.com"]}]
    assert not native_drop._dispatch_drop(Pasteboard(), None, callback)
