from retry import deliver


class CommitThenTimeout:
    def __init__(self):
        self.committed = []

    def __call__(self, payload):
        self.committed.append(payload)
        raise TimeoutError("acknowledgement lost after commit")


def test_delivery_retries_after_a_committed_write():
    writer = CommitThenTimeout()

    try:
        deliver(writer, "message")
    except TimeoutError:
        pass

    assert writer.committed == ["message", "message", "message"]
