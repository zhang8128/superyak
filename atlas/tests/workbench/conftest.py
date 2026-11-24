"""Shared fixtures for the workbench tests."""
import pytest


@pytest.fixture(autouse=True)
def lanes_free_before_each_test():
    """Each fixed lane (paper, model) holds its one request until that request's worker cleans up
    (research_sources._request_bytes), and the lanes are module state shared by every test here. So on a slow runner
    one test's timed-out drip can still hold the paper lane when the next test starts, and that test then reads "still
    finishing" where it expects its deadline (main 0d6a8a02, CI run 45401222159). Wait for both lanes first. A lane
    still held after 5 s is a worker that never cleaned up, which is a failure, not a wait."""
    from workbench.research_sources import _REQUEST_SLOTS
    for lane, slot in _REQUEST_SLOTS.items():
        assert slot.acquire(timeout=5), f"the {lane} lane's last worker never cleaned up"
        slot.release()
    yield
