"""Unit tests for LeaseManager."""

from runtime.leases import LeaseManager
from state.events import EventStore
from state.projection import LeaseProjector


def test_lease_grant_and_release(tmp_path):
    store = EventStore(tmp_path / "lease_test.db")
    mgr = LeaseManager(store, "p_lease")

    lease = mgr.request_lease("src/core/**", "agent_codex", task_id="t1")
    assert lease is not None
    assert lease.fencing_token == 1
    assert lease.holder == "agent_codex"

    events = store.read_all(project_id="p_lease")
    proj = LeaseProjector("p_lease")
    for e in events:
        proj.apply(e)

    active = proj.get_active_lease("src/core/**")
    assert active is not None
    assert active.fencing_token == 1

    # Release
    mgr.release_lease("src/core/**", "agent_codex", task_id="t1")
    events = store.read_all(project_id="p_lease")
    for e in events:
        proj.apply(e)

    assert proj.get_active_lease("src/core/**") is None
    store.close()
