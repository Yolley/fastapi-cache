up:
	@uv update

deps:
	@uv sync --all-groups

format: deps
	@uv run tox run -e format

lint: deps
	@uv run tox run -e lint

test: deps
	@uv run tox

test-parallel: deps
	@uv run tox run-parallel

build: clean deps
	@uv build

clean:
	@rm -rf ./dist

# aliases
check: lint
style: format
