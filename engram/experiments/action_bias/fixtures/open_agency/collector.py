def collect(events):
    return {event["kind"]: event["value"] for event in events}
