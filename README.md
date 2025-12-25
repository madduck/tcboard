[![Style and unit tests badge](https://github.com/madduck/tcboard/actions/workflows/0-testing.yml/badge.svg)](https://github.com/madduck/tcboard/actions/workflows/0-testing.yml)

# TCBoard — Server to collect and provide tournament data

TODO

## Contributing

To contribute, please ensure you have the appropriate dependencies installed:

```
pip install -e .[dev]
```

and then install the Git pre-commit hooks that ensure that any commits conform
with the coding-style used by this project.

```
pre-commit install
```

All code (except for the CLI) is 100% test-covered, and all
contributions are expected to keep this up. Use `pytest` to run the test suite.

Note that all code is typed, and typing is part of test-coverage.

## Known Problems

None at this point (but there will be some).

## TODO

In addition to various comments including the word "TODO" in the code, there are
a few things left to do:

* Test the CLI
* Test the HTTP APIs

## Legalese

`tcboard` is © 2024–6 martin f. krafft <tcboard@pobox.madduck.net>.

It is released under the terms of the MIT Licence.
