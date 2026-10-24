from __future__ import annotations

from tests.fakes import sample_mailbox


def test_find_unanswered_cruza_enviados() -> None:
    _fake, service, _account = sample_mailbox()
    payload = service.find_unanswered("vyrts", since="2026-10-01")
    uids = [item["uid"] for item in payload["messages"]]
    assert 10 in uids
    assert 13 in uids
    assert 11 not in uids
    assert 12 not in uids
    assert payload["sent_crosscheck"] is True


def test_find_unanswered_sin_carpeta_enviados() -> None:
    fake, service, account = sample_mailbox()
    del fake.folders["Sent"]
    renamed = type(account)(
        key=account.key,
        label=account.label,
        imap_host=account.imap_host,
        imap_port=account.imap_port,
        username=account.username,
        password=account.password,
        sent_folder="Sent",
    )
    service.accounts["vyrts"] = renamed
    payload = service.find_unanswered("vyrts")
    assert payload["sent_crosscheck"] is False
    assert 12 in [item["uid"] for item in payload["messages"]]


def test_list_threads_agrupa_por_references() -> None:
    _fake, service, _account = sample_mailbox()
    payload = service.list_threads("vyrts", limit=20)
    groups = {
        thread["root"]: [item["uid"] for item in thread["messages"]]
        for thread in payload["threads"]
    }
    assert groups["<presupuesto@ejemplo.test>"] == [10, 11]
    assert payload["threading"] == "references"
