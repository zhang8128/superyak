def summarize(episodes):
    return {"summary": " ".join(e["text"] for e in episodes), "count": len(episodes)}
