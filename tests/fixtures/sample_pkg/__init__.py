"""Sample package used by test_api_docs.py."""


def hello(name: str) -> str:
    """Return a greeting.

    Args:
        name: Who to greet.

    Returns:
        A greeting string.
    """
    return f"hello {name}"
