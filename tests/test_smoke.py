from myproject.main import run


def test_run_returns_startup_message() -> None:
    message = run()
    assert "running in" in message
