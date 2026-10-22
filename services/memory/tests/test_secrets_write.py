"""Writing secrets: set/replace/delete keep the file private, and read_fresh bypasses the cache."""

import json
import os
import stat

from dyson_memory.secrets import LocalSecretStore, read_fresh


def _store(tmp_path):
    p = tmp_path / "secrets.json"
    p.write_text(json.dumps({"core": {"channel_key": "abc"}}), "utf-8")
    p.chmod(0o600)
    return p, LocalSecretStore(p)


def test_set_names_get_and_read_fresh(tmp_path):
    p, s = _store(tmp_path)
    s.set("providers", "apinex_api_key", "sk-xyz")
    assert s.get("providers", "apinex_api_key") == "sk-xyz"
    assert s.names("providers") == ["apinex_api_key"]
    # a different process would use read_fresh; it sees the written value
    assert read_fresh(p, "providers", "apinex_api_key") == "sk-xyz"
    # the existing scope is untouched
    assert s.get("core", "channel_key") == "abc"
    # the file stays private after the rewrite
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o600


def test_set_replaces(tmp_path):
    _, s = _store(tmp_path)
    s.set("providers", "apinex_api_key", "old")
    s.set("providers", "apinex_api_key", "new")
    assert s.get("providers", "apinex_api_key") == "new"
    assert s.names("providers") == ["apinex_api_key"]


def test_delete_removes_name_and_empty_scope(tmp_path):
    p, s = _store(tmp_path)
    s.set("providers", "apinex_api_key", "sk")
    s.delete("providers", "apinex_api_key")
    assert s.names("providers") == []
    assert read_fresh(p, "providers", "apinex_api_key") is None
    assert "providers" not in json.loads(p.read_text("utf-8"))  # empty scope dropped


def test_read_fresh_missing_is_none(tmp_path):
    p, _ = _store(tmp_path)
    assert read_fresh(p, "providers", "apinex_api_key") is None
    assert read_fresh(tmp_path / "nope.json", "core", "x") is None
