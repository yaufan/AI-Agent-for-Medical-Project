.PHONY: install test data corpus eval-m1 eval-m2

install:
	pip install ./packages/lungnod -r services/cad-service/requirements-dev.txt
	pip install "./packages/rag[pdf,test]"
	pip install -e "./packages/tools[test]"

test:
	python -m pytest -q packages/lungnod/tests
	python -m pytest -q services/cad-service/tests
	python -m pytest -q packages/erpqms/tests
	python -m pytest -q packages/rag/tests
	python -m pytest -q packages/tools/tests

data:
	cd packages/erpqms && python -m erpqms.generate --out ../../data/synthetic/erpqms

corpus:
	python scripts/fetch_public_corpus.py

eval-m1: corpus
	python eval/run_retrieval.py

eval-m2:
	python eval/injection/run_injection.py --fail-on-created
