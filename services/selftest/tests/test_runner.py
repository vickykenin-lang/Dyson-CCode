"""The self-test runner: a command's exit code becomes a pass/fail, with its tail kept."""

import os

from dyson_selftest.runner import _run_one

ENV = dict(os.environ)  # a real PATH so `sh` resolves


def test_a_passing_command_is_ok_with_its_last_line():
    r = _run_one("ok", ["sh", "-c", "echo first; echo done"], ".", ENV, 10)
    assert r.ok is True
    assert r.summary == "done"


def test_a_failing_command_is_not_ok_and_keeps_the_tail():
    r = _run_one("bad", ["sh", "-c", "echo boom; exit 3"], ".", ENV, 10)
    assert r.ok is False
    assert r.summary == "boom"
    assert "boom" in r.tail


def test_a_missing_command_is_a_failure_not_a_crash():
    r = _run_one("x", ["dyson-no-such-command-xyz"], ".", ENV, 10)
    assert r.ok is False
    assert "could not run" in r.summary


def test_a_hang_times_out():
    r = _run_one("slow", ["sh", "-c", "sleep 5"], ".", ENV, 0.3)
    assert r.ok is False
    assert "timed out" in r.summary
