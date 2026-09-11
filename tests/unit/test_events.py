"""Unit tests for authoritative EventStore."""

import pytest
from state.events import EventStore
from state.hashing import canonical_json, compute_content_hash, compute_hash


def test_monotonic_event_ids(tmp_path):
    db_file = tmp_path / "test_events.db"
    store = EventStore(db_file)

    id1 = store.append(actor="orch", kind="project.created", project_id="p1", payload={"spec": {"name": "test"}})
    id2 = store.append(actor="orch", kind="task.created", project_id="p1", payload={"goal": "first task"}, task_id="t1")
    id3 = store.append(actor="agent_1", kind="task.submitted", project_id="p1", payload={"diff": "abc"}, task_id="t1")

    assert id1 == 1
    assert id2 == 2
    assert id3 == 3
    assert store.current_version("p1") == 3

    store.close()


def test_content_hash_stability():
    payload = {"z": 10, "a": [1, 2, 3], "nested": {"key": "val"}}
    hash1 = compute_content_hash(
        actor="orch",
        kind="project.created",
        project_id="p1",
        payload=payload,
    )
    hash2 = compute_content_hash(
        actor="orch",
        kind="project.created",
        project_id="p1",
        payload={"a": [1, 2, 3], "nested": {"key": "val"}, "z": 10},
    )
    assert hash1 == hash2


def test_read_after_and_filtering(tmp_path):
    store = EventStore(tmp_path / "filter.db")
    for i in range(5):
        store.append(actor="orch", kind="test.event", project_id="p1", payload={"index": i})
    for i in range(3):
        store.append(actor="orch", kind="test.event", project_id="p2", payload={"index": i})

    p1_events_after_2 = store.read_after(2, project_id="p1")
    assert len(p1_events_after_2) == 3
    assert [e.id for e in p1_events_after_2] == [3, 4, 5]

    p2_events = store.read_after(0, project_id="p2")
    assert len(p2_events) == 3
    assert [e.id for e in p2_events] == [6, 7, 8]

    store.close()


def test_invalid_append_rejected(tmp_path):
    store = EventStore(tmp_path / "reject.db")
    with pytest.raises(ValueError):
        store.append(actor="", kind="test", project_id="p1", payload={})
    with pytest.raises(ValueError):
        store.append(actor="orch", kind="", project_id="p1", payload={})
    with pytest.raises(ValueError):
        store.append(actor="orch", kind="test", project_id="", payload={})
    store.close()
