lint:
	black . --exclude venv
	mypy . --check-untyped-defs --exclude venv
	flake8 . --exclude=venv
style_check:
	black . --exclude venv --check
	mypy . --check-untyped-defs --exclude venv
	flake8 . --exclude=venv
ci:
	make test
test:
	python -m unittest discover .

pre-commit:
	make style_check
	make test

install_hook:
	echo "make pre-commit" > .git/hooks/pre-commit
	chmod +x .git/hooks/pre-commit