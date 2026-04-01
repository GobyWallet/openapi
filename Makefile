.PHONY: run dev watcher redis clean

run:
	uv run uvicorn openapi.api:app --host 0.0.0.0 --port 8000

dev:
	uv run uvicorn openapi.api:app --host 0.0.0.0 --port 8000 --reload

watcher:
	uv run python -m openapi.watcher

clean:
	rm -f wallet_*.db wallet_*.db-shm wallet_*.db-wal