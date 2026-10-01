from app.core.rate_limit import TokenRateLimiter


def test_limiter_rejects_requests_over_the_window_quota() -> None:
    now = 10.0
    limiter = TokenRateLimiter(2, 60, clock=lambda: now)

    assert limiter.allow("token-a") is True
    assert limiter.allow("token-a") is True
    assert limiter.allow("token-a") is False


def test_limiter_keeps_quotas_independent_per_token() -> None:
    limiter = TokenRateLimiter(1, 60, clock=lambda: 10)

    assert limiter.allow("token-a") is True
    assert limiter.allow("token-b") is True
