# Cache policy

Callers disagree about whether `None` means that a key is missing or that its
value has expired. The current contract does not resolve that distinction.
