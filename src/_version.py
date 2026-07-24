"""Single source of truth for the app version. Referenced from the CLI
(`--version`), the web UI (footer + `/api/version`), and CHANGELOG.md —
bump this alongside a CHANGELOG entry and a matching git tag, not on its own.
"""

__version__ = "1.1.0"
