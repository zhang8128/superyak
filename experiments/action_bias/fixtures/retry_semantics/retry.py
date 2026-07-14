def deliver(write, payload, attempts=3):
    for _ in range(attempts):
        try:
            return write(payload)
        except TimeoutError:
            continue
    raise TimeoutError("delivery failed")
