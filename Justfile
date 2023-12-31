test:
	poetry run pytest --cov=src/ --cov-report html

lint:
	poetry run ruff src/ tests/
	poetry run black --check src/ tests/

release type:  # patch, minor, major
	poetry version {{type}}
	poetry build
	#poetry run mkdocs gh-deploy
	poetry publish
	git commit -am "release $(poetry version -s)"
	git tag v$(poetry version -s)
	git push
	git push --tags
	gh release create v$(poetry version -s) -F docs/changelog.md