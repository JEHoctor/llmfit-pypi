# Run the test suite
test:
    uv run pytest

# Build a wheel for the current platform (useful for local testing)
build:
    uv build --wheel
