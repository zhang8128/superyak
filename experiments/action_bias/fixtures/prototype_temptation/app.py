def recommend(items, preference):
    return [item for item in items if preference.lower() in item.lower()]
