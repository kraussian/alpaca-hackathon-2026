import json

from agent_pkg.audit import AuditLog, scrub


def test_scrub_removes_account_numbers():
    assert "PAEXAMPLE1234" not in scrub("account PAEXAMPLE1234 is active")
    assert "<account>" in scrub("account PAEXAMPLE1234 is active")


def test_scrub_removes_api_keys():
    out = scrub("key PKTESTKEY0123456789AB here")
    assert "PKTESTKEY0123456789AB" not in out
    assert "<key>" in out


def test_scrub_leaves_ordinary_text_alone():
    text = "bought SPY260918C00760000 at 12.00"
    assert scrub(text) == text


def test_write_appends_one_json_object_per_call(tmp_path):
    log = AuditLog(session_id="test", directory=tmp_path)
    log.write("decision", reasoning="looks cheap")
    log.write("gate_verdict", allowed=False, reasons=["kill switch is engaged"])

    lines = log.path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["event"] == "decision"
    assert first["session_id"] == "test"
    assert first["reasoning"] == "looks cheap"
    assert "timestamp" in first


def test_write_scrubs_nested_values(tmp_path):
    log = AuditLog(session_id="test", directory=tmp_path)
    log.write("submission", detail={"account": "PAEXAMPLE1234"})
    written = log.path.read_text(encoding="utf-8")
    assert "PAEXAMPLE1234" not in written
    assert "<account>" in written
