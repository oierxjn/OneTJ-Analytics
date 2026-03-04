def mask_value(value: str) -> str:
    if len(value) <= 2:
        return "*" * len(value)
    return f"{value[0]}{'*' * (len(value) - 2)}{value[-1]}"


def mask_sensitive_payload(payload: dict[str, str]) -> dict[str, str]:
    masked = dict(payload)
    for key in ("userid", "username"):
        if key in masked:
            masked[key] = mask_value(masked[key])
    return masked

