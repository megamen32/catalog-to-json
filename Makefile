.PHONY: check
check:
	timeout 180s sh -c 'uv sync --locked && uv run pytest -q && uv build --out-dir .tmp/dist'
