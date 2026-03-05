def mask_value(value: str) -> str:
    if len(value) <= 2:
        return "*" * len(value)
    return f"{value[0]}{'*' * (len(value) - 2)}{value[-1]}"


def mask_sensitive_payload(payload: dict[str, object]) -> dict[str, object]:
    masked: dict[str, object] = dict(payload)
    for key in ("userid", "username"):
        raw = masked.get(key)
        if isinstance(raw, str):
            masked[key] = mask_value(raw)
    return masked
