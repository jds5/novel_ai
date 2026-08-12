import gzip
import json

from novel_ai.storage import LocalObjectStore


def test_local_object_store_is_content_addressed_and_compressed(tmp_path) -> None:
    store = LocalObjectStore(tmp_path)

    first = store.put_json("responses", {"text": "雨落下来。", "count": 1})
    second = store.put_json("responses", {"count": 1, "text": "雨落下来。"})

    assert first == second
    relative = first.uri.removeprefix("objects://")
    stored_path = tmp_path / relative
    assert stored_path.exists()
    assert json.loads(gzip.decompress(stored_path.read_bytes())) == {
        "count": 1,
        "text": "雨落下来。",
    }
