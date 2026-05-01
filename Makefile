.PHONY: quickstart test bench up
quickstart:
	pip install -r requirements.txt

test:
	python -m unittest -v

bench:
	BENCHMARK_GATE=0.95 python benchmarks/evaluate.py

up:
	docker compose up --build
