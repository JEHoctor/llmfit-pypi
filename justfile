# List available commands
default:
    @just --list

# Run the test suite
test:
    uv run pytest

# Format
format:
    uv run ruff format hatch_build.py build_wheels.py src/ tests/

# Lint
lint:
    uv run ruff check hatch_build.py build_wheels.py src/ tests/

# Type check
typecheck:
    uv run ty check hatch_build.py build_wheels.py src/
    uv run ty check tests/

# Build a wheel for the current platform (useful for local testing)
build:
    uv build --wheel
