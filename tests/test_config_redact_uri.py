from src.config import redact_uri


def test_redacts_mongodb_atlas_style_uri():
    uri = "mongodb+srv://exampleuser:examplepass@cluster0.abc123.mongodb.net/"
    redacted = redact_uri(uri)
    assert "examplepass" not in redacted
    assert "exampleuser" not in redacted
    assert redacted == "mongodb+srv://***:***@cluster0.abc123.mongodb.net/"


def test_redacts_redis_uri_with_password():
    assert redact_uri("redis://:hunter2@myredis.example.com:6379/0") == "redis://***:***@myredis.example.com:6379/0"


def test_leaves_credential_free_uris_unchanged():
    assert redact_uri("mongodb://localhost:27017") == "mongodb://localhost:27017"
    assert redact_uri("redis://localhost:6379/0") == "redis://localhost:6379/0"
