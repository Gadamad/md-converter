"""Regression coverage for autosaved queues and cross-process worker exclusion."""

import importlib.util
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "src"))


@pytest.fixture
def store_type():
    def construct(path):
        assert importlib.util.find_spec("queue_store") is not None, "durable queue store is missing"
        from queue_store import QueueStore
        return QueueStore(path)
    return construct


@pytest.fixture
def store(store_type, tmp_path):
    return store_type(tmp_path / "queues.sqlite3")


def text_item(text="Notes", **extra):
    return {"kind": "text", "source": text, "title": text, **extra}


def test_inbox_and_active_collection_persist_after_reopen(store_type, tmp_path):
    path = tmp_path / "nested" / "queues.sqlite3"
    original = store_type(path)
    inbox = original.active_id
    assert original.state() == {
        "active_id": inbox,
        "queues": [{"id": inbox, "name": "Inbox"}],
        "items": [], "waiting": 0, "failed": 0, "done": 0, "total": 0,
    }
    collection = original.create_queue("  Reading  ")
    original.add_items(collection, [text_item()])
    original.rename_queue(collection, "Research")
    reopened = store_type(path)
    assert reopened.active_id == collection
    assert reopened.state()["queues"] == [
        {"id": inbox, "name": "Inbox"}, {"id": collection, "name": "Research"}
    ]
    reopened.select_queue(inbox)
    assert original.active_id == inbox
    assert len(original.items(collection)) == 1


def test_item_defaults_stable_order_and_full_results_persist(store_type, tmp_path):
    path = tmp_path / "queues.sqlite3"
    original = store_type(path)
    original.add_items(original.active_id, [text_item("First"), text_item("Second")])
    first, second = original.items(original.active_id)
    assert first == {
        "id": first["id"], "queue_id": original.active_id,
        "kind": "text", "source": "First", "title": "First", "group_name": None,
        "status": "waiting", "error": None, "output_path": None, "word_count": 0,
        "options": {}, "checkpoint_path": None, "receipt_path": None,
    }
    original.update_item(first["id"], status="done", output_path="/tmp/first.md",
                         word_count=17, options={"output_dir": "/tmp", "nested": [True]},
                         checkpoint_path="/tmp/job.json", receipt_path="/tmp/receipt.json")
    original.update_item(second["id"], status="failed", error="Missing source")
    reopened = store_type(path)
    state = reopened.state()
    assert [item["id"] for item in state["items"]] == [first["id"], second["id"]]
    assert (state["waiting"], state["failed"], state["done"], state["total"]) == (0, 1, 1, 2)
    restored = reopened.get_item(first["id"])
    assert restored["options"] == {"output_dir": "/tmp", "nested": [True]}
    assert restored["word_count"] == 17
    assert restored["receipt_path"] == "/tmp/receipt.json"


def test_sources_deduplicate_per_collection_without_losing_url_queries(store, tmp_path):
    queue_id = store.active_id
    source = tmp_path / "input.pdf"
    source.touch()
    alias = tmp_path / "alias.pdf"
    alias.symlink_to(source)
    assert store.add_items(queue_id, [
        {"kind": "file", "source": str(source), "title": "Input"},
        {"kind": "file", "source": str(alias), "title": "Alias"},
        {"kind": "url", "source": "https://example.test/page?a=1", "title": "One"},
        {"kind": "url", "source": "https://example.test/page?a=2", "title": "Two"},
        text_item("Text"), text_item("Text"), text_item("Text "),
    ]) == 5
    assert store.add_items(queue_id, [text_item("Text")]) == 0
    other = store.create_queue("Other")
    assert store.add_items(other, [text_item("Text")]) == 1


def test_two_instances_and_threads_never_lose_additions(store_type, tmp_path):
    path = tmp_path / "queues.sqlite3"
    first, second = store_type(path), store_type(path)
    queue_id = first.active_id
    # update_item uses independent connections, including worker threads.
    first.add_items(queue_id, [text_item(str(index)) for index in range(30)])
    ids = [item["id"] for item in first.items(queue_id)]
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(lambda pair: pair[0].update_item(pair[1], status="done"),
                      [(first if index % 2 else second, item_id)
                       for index, item_id in enumerate(ids)]))
    assert second.state()["done"] == 30
    second.add_items(queue_id, [text_item("Another")])
    assert first.state()["total"] == 31


def test_atomic_batch_update_rolls_back_if_an_item_is_missing(store):
    store.add_items(store.active_id, [text_item("One"), text_item("Two")])
    first, second = store.items(store.active_id)
    with pytest.raises(KeyError):
        store.update_items([first["id"], "missing", second["id"]], status="done")
    assert store.state()["waiting"] == 2
    store.update_items([first["id"], second["id"]], status="failed", error="Offline")
    assert store.state()["failed"] == 2


def test_failed_write_rolls_back_entire_addition(store, tmp_path):
    # A real SQLite write failure must reach the caller and preserve the batch.
    with sqlite3.connect(tmp_path / "queues.sqlite3") as connection:
        connection.execute("CREATE TRIGGER reject_item BEFORE INSERT ON items "
                           "WHEN NEW.title = 'Reject' BEGIN SELECT RAISE(ABORT, 'disk write rejected'); END")
    with pytest.raises(sqlite3.DatabaseError, match="disk write rejected"):
        store.add_items(store.active_id, [text_item("Keep"), text_item("Reject")])
    assert store.items(store.active_id) == []


@pytest.mark.parametrize("name", ["", "   ", "a" * 121, "bad\nname", "bad\x00name", None, 17])
def test_invalid_names_cannot_create_or_rename_collections(store, name):
    with pytest.raises((ValueError, TypeError)):
        store.create_queue(name)
    with pytest.raises((ValueError, TypeError)):
        store.rename_queue(store.active_id, name)
    assert [queue["name"] for queue in store.state()["queues"]] == ["Inbox"]


def test_duplicate_names_and_unknown_queues_do_not_change_active_queue(store):
    original = store.active_id
    with pytest.raises(ValueError):
        store.create_queue("inbox")
    with pytest.raises(KeyError):
        store.select_queue("missing")
    with pytest.raises(KeyError):
        store.rename_queue("missing", "New")
    with pytest.raises(KeyError):
        store.add_items("missing", [text_item()])
    assert store.active_id == original


@pytest.mark.parametrize("changes", [
    {"status": "lost"}, {"word_count": -1}, {"options": []},
    {"options": {"not_json": object()}}, {"id": "replace"},
    {"source": ""}, {"title": None}, {"word_count": "3"},
])
def test_invalid_item_updates_leave_existing_item_untouched(store, changes):
    store.add_items(store.active_id, [text_item()])
    original = store.items(store.active_id)[0]
    with pytest.raises((ValueError, TypeError)):
        store.update_item(original["id"], **changes)
    assert store.get_item(original["id"]) == original


def test_invalid_addition_does_not_partially_save_batch(store):
    with pytest.raises(ValueError):
        store.add_items(store.active_id, [text_item("Valid"), {"kind": "bad", "source": "x", "title": "X"}])
    assert store.state()["total"] == 0


def test_clear_completed_and_remove_preserve_pending_items(store):
    store.add_items(store.active_id, [text_item("Done"), text_item("Fail"), text_item("Wait")])
    done, failed, waiting = store.items(store.active_id)
    store.update_item(done["id"], status="done")
    store.update_item(failed["id"], status="failed")
    store.clear_queue(store.active_id, completed_only=True)
    assert [item["id"] for item in store.items(store.active_id)] == [failed["id"], waiting["id"]]
    store.remove_item(failed["id"])
    assert store.state()["waiting"] == 1
    store.clear_queue(store.active_id)
    assert store.state()["total"] == 0


def test_worker_lock_excludes_other_workers_and_ui_mutations(store_type, tmp_path):
    path = tmp_path / "queues.sqlite3"
    store, other = store_type(path), store_type(path)
    store.add_items(store.active_id, [text_item()])
    item_id = store.items(store.active_id)[0]["id"]
    with store.worker_lock():
        with pytest.raises(RuntimeError, match="(?i)(worker|running|busy)"):
            with other.worker_lock():
                pytest.fail("a second worker acquired the lock")
        for action in [lambda: other.create_queue("Blocked"),
                       lambda: other.rename_queue(other.active_id, "Blocked"),
                       lambda: other.select_queue(other.active_id),
                       lambda: other.add_items(other.active_id, [text_item("Blocked")]),
                       lambda: other.remove_item(item_id),
                       lambda: other.delete_queue(other.active_id),
                       lambda: other.clear_queue(other.active_id)]:
            with pytest.raises(RuntimeError):
                action()
        store.update_item(item_id, status="processing")
        assert other.recover_interrupted() == 0
        assert other.get_item(item_id)["status"] == "processing"
    assert other.recover_interrupted() == 1
    assert other.get_item(item_id)["status"] == "waiting"
    with other.worker_lock():
        pass


def test_recovery_preserves_results_and_saved_work_options(store):
    store.add_items(store.active_id, [text_item("Success"), text_item("Crash"), text_item("Failure")])
    success, crash, failure = store.items(store.active_id)
    store.update_item(success["id"], status="done", output_path="/tmp/result.md")
    store.update_item(crash["id"], status="processing", checkpoint_path="/tmp/checkpoint.json",
                      options={"output_dir": "/tmp/original"})
    store.update_item(failure["id"], status="failed", error="Missing")
    assert store.recover_interrupted() == 1
    assert store.get_item(success["id"])["status"] == "done"
    assert store.get_item(failure["id"])["status"] == "failed"
    restored = store.get_item(crash["id"])
    assert restored["checkpoint_path"] == "/tmp/checkpoint.json"
    assert restored["options"] == {"output_dir": "/tmp/original"}


def test_source_relocation_is_canonical_and_deduplicated(store, tmp_path):
    store.add_items(store.active_id, [
        {"kind": "file", "source": str(tmp_path / "old.pdf"), "title": "Old"},
        {"kind": "file", "source": str(tmp_path / "new.pdf"), "title": "New"},
    ])
    old, new = store.items(store.active_id)
    with pytest.raises((sqlite3.IntegrityError, ValueError)):
        store.update_item(old["id"], source=new["source"])
    assert store.get_item(old["id"])["source"] == old["source"]
    store.update_item(old["id"], source=str(tmp_path / "sub" / ".." / "located.pdf"), title="Located")
    assert store.get_item(old["id"])["source"] == str(tmp_path / "located.pdf")


def test_corrupt_database_is_not_overwritten(store_type, tmp_path):
    path = tmp_path / "queues.sqlite3"
    contents = b"not a database: do not overwrite"
    path.write_bytes(contents)
    with pytest.raises(sqlite3.DatabaseError):
        store_type(path)
    assert path.read_bytes() == contents


def test_unknown_database_schema_is_not_repurposed(store_type, tmp_path):
    path = tmp_path / "queues.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE unrelated (value TEXT)")
        connection.execute("INSERT INTO unrelated VALUES ('valuable')")
    with pytest.raises((RuntimeError, sqlite3.DatabaseError)):
        store_type(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT value FROM unrelated").fetchall() == [("valuable",)]
        assert connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == [("unrelated",)]


def test_concurrent_first_open_creates_exactly_one_inbox(store_type, tmp_path):
    path = tmp_path / "queues.sqlite3"
    with ThreadPoolExecutor(max_workers=8) as pool:
        stores = list(pool.map(lambda _: store_type(path), range(8)))
    assert len({store.active_id for store in stores}) == 1
    assert len(stores[0].state()["queues"]) == 1


def test_readding_successful_source_preserves_result(store):
    item = text_item("Already converted")
    store.add_items(store.active_id, [item])
    item_id = store.items(store.active_id)[0]["id"]
    store.update_item(item_id, status="done", output_path="/tmp/finished.md", word_count=12)
    assert store.add_items(store.active_id, [item]) == 0
    assert store.get_item(item_id)["status"] == "done"
    assert store.get_item(item_id)["output_path"] == "/tmp/finished.md"


def test_worker_lock_is_cross_process_and_released_after_process_crash(store_type, tmp_path):
    path = tmp_path / "queues.sqlite3"
    store = store_type(path)
    store.add_items(store.active_id, [text_item()])
    item_id = store.items(store.active_id)[0]["id"]
    script = (
        "import os, sys\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "from queue_store import QueueStore, QueueBusyError\n"
        "store = QueueStore(sys.argv[2])\n"
        "try:\n"
        "    with store.worker_lock():\n"
        "        store.update_item(sys.argv[3], status='processing')\n"
        "        os._exit(0)\n"
        "except QueueBusyError:\n"
        "    sys.exit(11)\n"
    )
    command = [sys.executable, "-c", script, str(PROJECT_DIR / "src"), str(path), item_id]
    with store.worker_lock():
        result = subprocess.run(command, capture_output=True, text=True, timeout=10)
        assert result.returncode == 11, result.stderr
    result = subprocess.run(command, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert store.get_item(item_id)["status"] == "processing"
    assert store.recover_interrupted() == 1
    assert store.get_item(item_id)["status"] == "waiting"


def test_delete_selected_queue_restores_another_and_preserves_files(store, store_type, tmp_path):
    inbox = store.active_id
    store.add_items(inbox, [text_item("Keep me")])
    source, output = tmp_path / "source.txt", tmp_path / "converted.md"
    source.write_text("Original")
    output.write_text("Converted")
    removed = store.create_queue("Remove me")
    store.add_items(removed, [{"kind": "file", "source": str(source), "title": source.name}])
    store.update_item(store.items(removed)[0]["id"], status="done", output_path=str(output))
    store.delete_queue(removed)
    restored = store_type(store.path).state()
    assert restored["active_id"] == inbox
    assert restored["queues"] == [{"id": inbox, "name": "Inbox"}]
    assert restored["items"][0]["source"] == "Keep me"
    with sqlite3.connect(store.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM items WHERE queue_id = ?", (removed,)).fetchone()[0] == 0
    assert source.read_text() == "Original"
    assert output.read_text() == "Converted"


def test_delete_inactive_queue_keeps_current_selection(store):
    inbox = store.active_id
    current = store.create_queue("Current")
    store.add_items(current, [text_item("Current work")])
    store.delete_queue(inbox)
    assert store.active_id == current
    assert store.state()["total"] == 1


@pytest.mark.parametrize("name", ["Inbox", "Renamed inbox"])
def test_delete_last_queue_creates_empty_inbox(store, store_type, name):
    removed = store.active_id
    store.rename_queue(removed, name)
    store.add_items(removed, [text_item()])
    store.delete_queue(removed)
    restored = store_type(store.path).state()
    assert restored["active_id"] != removed
    assert restored["queues"] == [{"id": restored["active_id"], "name": "Inbox"}]
    assert restored["total"] == 0


@pytest.mark.parametrize("last_queue", [True, False])
def test_delete_failure_rolls_back_items_selection_and_collection(store, last_queue):
    if not last_queue:
        store.create_queue("Another queue")
    store.add_items(store.active_id, [text_item("Must survive")])
    before = store.state()
    with sqlite3.connect(store.path) as connection:
        connection.execute("CREATE TRIGGER reject_delete BEFORE DELETE ON queues "
                           "BEGIN SELECT RAISE(ABORT, 'Cannot delete queue'); END")
    with pytest.raises(sqlite3.DatabaseError, match="Cannot delete queue"):
        store.delete_queue(store.active_id)
    assert store.state() == before


def test_delete_missing_queue_preserves_everything(store):
    before = store.state()
    with pytest.raises(KeyError):
        store.delete_queue("missing")
    assert store.state() == before
