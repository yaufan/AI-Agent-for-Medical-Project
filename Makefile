.PHONY: install test data

install:
	pip install ./packages/lungnod -r services/cad-service/requirements-dev.txt

test:
	python -m pytest -q packages/lungnod/tests
	python -m pytest -q services/cad-service/tests
	python -m pytest -q packages/erpqms/tests

data:
	cd packages/erpqms && python -m erpqms.generate --out ../../data/synthetic/erpqms
