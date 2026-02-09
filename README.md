# Planet Harvester

Harvests collections from the Planet catalogue. Planet is large and contains many items - items need to be collected
via the [API](https://github.com/EO-DataHub/stac-planet-api).

It is designed to operate as part of a data pipeline, generating STAC collections for Planet data, storing the
results in S3 and sending pulsar messages with details of updated files. It sends messages back to Pulsar to notify
downstream services of the new or updated catalogue entries.

Harvested collections can be found in`/commercial/catalogs/planet`


## Getting started

### Prerequisites

- [uv](https://docs.astral.sh/uv/)

### Install via makefile

```commandline
make setup
```

This will install dependencies via `uv sync` and set up `pre-commit` hooks.

It's safe and fast to run `make setup` repeatedly as it will only update these things if
they have changed.

After `make setup` you can run `make pre-commit` to run pre-commit checks on staged changes and
`make pre-commit-all` to run them on all files. This replicates the linter checks that
run from GitHub actions.

## Building and testing

This component uses `pytest` tests and `ruff` for linting and formatting, and `pyright` for type checking.

A number of `make` targets are defined:
* `make test`: run tests continuously (via `pytest-watcher`)
* `make testonce`: run tests once
* `make check`: run all linters, formatters, type checking and pyproject validation
* `make format`: auto-fix lint issues and reformat code
* `make dockerbuild`: build a `latest` Docker image (use `make dockerbuild VERSION=1.2.3` for a release image)
* `make dockerpush`: push a `latest` Docker image (again, you can add `VERSION=1.2.3`) - normally this should be done
  only via the build system and its GitHub actions.

## Managing dependencies

Dependencies are specified in `pyproject.toml`. To add a new dependency:

```commandline
uv add <package-name>
```

To add a dev dependency:

```commandline
uv add --dev <package-name>
```

To update all dependencies to their latest compatible versions:

```commandline
make update
```

The `uv.lock` file is committed to the repository to ensure reproducible builds.

## Releasing

Ensure that `make check` and `make testonce` work correctly and produce no further changes to code formatting before
continuing.

Releases tagged `latest` and targeted at development environments can be created from the `main` branch. Releases for
installation in non-development environments should be created from a Git tag named using semantic versioning. For
example, using

* `git tag 1.2.3`
* `git push --tags`

Docker images will be built automatically by GitHub Actions after pushing.

## Configuration

The Harvest Transformer is configured through environment variables

### Environment variables

- `MINIMUM_MESSAGE_ENTRIES` - minimum number of entries per message
- `PLANET_API_KEYS` - A colon-separated string of Planet API keys
- `COMMERCIAL_CATALOGUE_ROOT` - root for the commercial data path
- `VALID_COLLECTIONS` - a comma-separated list of valid Planet collections
- `PLANET_API_URL` - URL for the Planet API


## Pulsar Messages

### Outgoing Pulsar Messages (`harvested` topic)

After processing, the service sends a message to the `harvested` topic.

```json
{
  "id": "<unique_id>",
  "workspace": "<workspace_name>",
  "bucket_name": "<destination_s3_bucket>",
  "source": "<source_url_prefix>",
  "target": "<target_url_prefix>",
  "updated_keys": ["<list/of/transformed/keys>"],
  "deleted_keys": ["<list/of/deleted/keys>"],
  "added_keys": ["<list/of/newly/added/keys>"]
}
```

- `bucket_name`: S3 bucket where transformed files are stored (may be different from the source).
- `updated_keys`, `deleted_keys`, `added_keys`: Refer to the updated, deleted, or added files in the output catalogue.

**Note:** The service may also send "empty" catalogue change messages (with no updated, deleted, or added keys) to indicate no file changes.

## Usage

The service is typically run as part of a data pipeline, but you can invoke it directly for testing or development.

Run from the command line:

```sh
uv run python -m planet_harvester harvest workspace_name catalog_name s3_bucket_name
```


## Development

- Code is in `planet_harvester/`.
- Formatting and linting: [Ruff](https://docs.astral.sh/ruff/)
- Type checking: [Pyright](https://github.com/microsoft/pyright)
- Pre-commit checks are installed with `make setup`.

Useful Makefile targets:

- `make setup`: Set up or update the dev environment.
- `make test`: Run tests continuously.
- `make testonce`: Run tests once.
- `make check`: Run all linters, type checking and validation.
- `make format`: Auto-fix lint issues and reformat code.
- `make dockerbuild`: Build a Docker image.
- `make dockerpush`: Push a Docker image.


## License

This project is licensed under the United Kingdom Research and Innovation BSD Licence. See [LICENSE](LICENSE) for details.
