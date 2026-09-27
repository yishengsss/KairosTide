import json
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from kairos.adapters.persistence.sqlite import SqliteRepository
from kairos.application.assistant_tasks import ModelTurn, ToolCall
from kairos.application.drafts import DraftService
from kairos.application.draft_commit import DraftCommitService
from kairos.domain.drafts import Candidate
from kairos.domain.events import RecurrenceRule
from datetime import date, time
from kairos.main import create_app


NOW = datetime(2026, 9, 26, 12, tzinfo=UTC)


class FixedClock:
    def now(self):
        return NOW


class FixedModel:
    def __init__(self, *turns):
        self.turns = list(turns)

    def complete(self, messages, tools):
        return self.turns.pop(0) if self.turns else ModelTurn("请补充缺少的信息。")


def rigid_draft_call():
    return ToolCall(call_id="rigid-1", name="create_rigid_event_draft", arguments_json=json.dumps({}))


def client_for(tmp_path, owner="local"):
    path = tmp_path / "kairos.db"
    return TestClient(create_app(str(path), clock=FixedClock(), owner_id=owner)), SqliteRepository(path)


def post_draft(client, text, key="new-event"):
    return client.post("/api/v1/drafts", headers={"Idempotency-Key": key}, json={
        "conversation_id": "conversation-1", "source_message_id": "message-1",
        "intent": "create_rigid_event", "text": text, "timezone": "Asia/Shanghai",
    })


def test_explicit_meeting_stays_draft_until_confirmed(tmp_path):
    client, repo = client_for(tmp_path)
    created = post_draft(client, "明天下午两点开项目会，一个小时")
    assert created.status_code == 200
    draft = created.json()
    assert draft["status"] == "ready"
    assert draft["candidates"][0]["title"] == "项目会"
    assert draft["candidates"][0]["start_at"] == "2026-09-27T14:00:00+08:00"
    assert draft["candidates"][0]["end_at"] == "2026-09-27T15:00:00+08:00"
    assert repo.list_events("local") == []
    assert post_draft(client, "明天下午两点开项目会，一个小时").json()["draft_id"] == draft["draft_id"]

    saved = client.post(f"/api/v1/drafts/{draft['draft_id']}/commit", headers={"Idempotency-Key": "commit-1"}, json={
        "revision": draft["revision"], "confirmed_candidate_ids": [draft["candidates"][0]["candidate_id"]],
        "confirmation_digest": draft["confirmation_digest"], "conflict_acceptance": None,
    })
    assert saved.status_code == 200
    assert len(repo.list_events("local")) == 1
    assert client.get(f"/api/v1/drafts/{draft['draft_id']}").json()["status"] == "committed"


def test_missing_clock_time_requires_clarification_and_stale_confirmation_fails(tmp_path):
    client, repo = client_for(tmp_path)
    created = post_draft(client, "下周二下午上课", "incomplete")
    assert created.status_code == 200
    draft = created.json()
    assert draft["status"] == "needs_clarification"
    assert "start_at" in draft["candidates"][0]["missing_fields"]
    assert repo.list_events("local") == []
    before = client.post(f"/api/v1/drafts/{draft['draft_id']}/commit", headers={"Idempotency-Key": "too-early"}, json={
        "revision": 1, "confirmed_candidate_ids": [draft["candidates"][0]["candidate_id"]],
        "confirmation_digest": draft["confirmation_digest"], "conflict_acceptance": None,
    })
    assert before.status_code in (409, 422)
    completed = client.post(f"/api/v1/drafts/{draft['draft_id']}/clarifications", headers={"Idempotency-Key": "clarify"}, json={
        "revision": 1, "answers": {"start_at": "2026-09-29T14:00:00+08:00", "end_at": "2026-09-29T15:00:00+08:00"},
    })
    assert completed.status_code == 200
    assert completed.json()["status"] == "ready"
    assert completed.json()["confirmation_digest"] != draft["confirmation_digest"]
    assert repo.list_events("local") == []


def test_draft_patch_requires_targeted_candidate_and_revision(tmp_path):
    client, _ = client_for(tmp_path)
    draft = post_draft(client, "2026-09-27 14:00-15:00 项目会", "patch-source").json()
    candidate_id = draft["candidates"][0]["candidate_id"]
    patched = client.patch(f"/api/v1/drafts/{draft['draft_id']}", headers={"Idempotency-Key": "patch-one"}, json={
        "revision": 1, "operations": [{"action": "update_candidate", "candidate_id": candidate_id,
            "changes": {"location": "教学楼A"}}],
    })
    assert patched.status_code == 200
    assert patched.json()["candidates"][0]["location"] == "教学楼A"
    assert patched.json()["revision"] == 2
    stale = client.patch(f"/api/v1/drafts/{draft['draft_id']}", headers={"Idempotency-Key": "patch-two"}, json={
        "revision": 1, "operations": [{"action": "update_candidate", "candidate_id": candidate_id,
            "changes": {"title": "覆盖"}}],
    })
    assert stale.status_code == 409


def test_proposal_is_review_only_until_confirmed_and_instance_is_default_scope(tmp_path):
    client, repo = client_for(tmp_path)
    draft = post_draft(client, "2026-09-27 14:00-15:00 项目会", "proposal-source").json()
    client.post(f"/api/v1/drafts/{draft['draft_id']}/commit", headers={"Idempotency-Key": "save"}, json={
        "revision": 1, "confirmed_candidate_ids": [draft["candidates"][0]["candidate_id"]],
        "confirmation_digest": draft["confirmation_digest"], "conflict_acceptance": None,
    })
    occurrence = repo.list_occurrences("local", NOW, NOW + timedelta(days=3))[0]
    proposed = client.post("/api/v1/event-change-proposals", headers={"Idempotency-Key": "change-propose"}, json={
        "target_id": occurrence.occurrence_id, "scope": "occurrence", "expected_version": occurrence.version,
        "action": "update", "changes": {"title": "项目评审会"}, "source_message_id": "message-2",
    })
    assert proposed.status_code == 200
    assert repo.list_occurrences("local", NOW, NOW + timedelta(days=3))[0].title == "项目会"
    assert proposed.json()["target_id"] == occurrence.occurrence_id

    confirmed = client.post(f"/api/v1/event-change-proposals/{proposed.json()['proposal_id']}/commit",
        headers={"Idempotency-Key": "confirm-change"}, json={"revision": proposed.json()["revision"],
        "confirmation_digest": proposed.json()["confirmation_digest"], "source_action_id": "confirm-2"})
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "committed"
    assert repo.list_occurrences("local", NOW, NOW + timedelta(days=3))[0].title == "项目评审会"
    assert client.post(f"/api/v1/event-change-proposals/{proposed.json()['proposal_id']}/commit",
        headers={"Idempotency-Key": "confirm-change"}, json={"revision": proposed.json()["revision"],
        "confirmation_digest": proposed.json()["confirmation_digest"], "source_action_id": "confirm-2"}).json() == confirmed.json()


def test_recurring_instance_delete_preserves_next_week_and_series_delete_is_explicit(tmp_path):
    client, repo = client_for(tmp_path)
    rule = RecurrenceRule("weekly", date(2026, 9, 28), date(2026, 10, 5), (1,), time(14), time(15), 0)
    candidate = Candidate("course", "软件工程", "教学楼A", datetime(2026, 9, 28, 6, tzinfo=UTC),
                          datetime(2026, 9, 28, 7, tzinfo=UTC), "Asia/Shanghai", rule)
    draft = DraftService(repo, FixedClock()).create("local", [candidate], "message-series")
    DraftCommitService(repo, FixedClock()).commit("local", draft.draft_id, 1, ["course"], draft.confirmation_digest, "series-save")
    occurrences = repo.list_occurrences("local", NOW, NOW + timedelta(days=14))
    first = client.post("/api/v1/event-change-proposals", headers={"Idempotency-Key": "instance-propose"}, json={
        "target_id": occurrences[0].occurrence_id, "scope": "occurrence", "expected_version": 1,
        "action": "delete", "changes": None, "source_message_id": "message-delete-instance"})
    assert first.status_code == 200
    p = first.json()
    removed = client.post(f"/api/v1/event-change-proposals/{p['proposal_id']}/commit",
        headers={"Idempotency-Key": "instance-commit"}, json={"revision": 1,
            "confirmation_digest": p["confirmation_digest"], "source_action_id": "confirm-instance"})
    assert removed.status_code == 200
    assert [o.disposition for o in repo.list_occurrences("local", NOW, NOW + timedelta(days=14))] == ["cancelled", "scheduled"]

    event = repo.list_events("local")[0]
    whole = client.post("/api/v1/event-change-proposals", headers={"Idempotency-Key": "series-propose"}, json={
        "target_id": event.event_id, "scope": "series", "expected_version": event.version,
        "action": "delete", "changes": None, "source_message_id": "message-delete-series"})
    assert whole.status_code == 200
    assert len(repo.list_events("local")) == 1
    q = whole.json()
    closed = client.post(f"/api/v1/event-change-proposals/{q['proposal_id']}/commit",
        headers={"Idempotency-Key": "series-commit"}, json={"revision": 1,
            "confirmation_digest": q["confirmation_digest"], "source_action_id": "confirm-series"})
    assert closed.status_code == 200
    assert repo.list_events("local") == []
    assert repo.list_occurrences("local", NOW, NOW + timedelta(days=14)) == []


def test_assistant_model_classifies_explicit_event_and_returns_uncommitted_draft(tmp_path):
    path = tmp_path / "kairos.db"
    model = FixedModel(ModelTurn(None, (rigid_draft_call(),)), ModelTurn(None, (rigid_draft_call(),)))
    with TestClient(create_app(str(path), clock=FixedClock(), assistant_task_model=model)) as client:
        response = client.post("/api/v1/assistant/chat", json={"client_message_id": "utterance-1",
            "timezone": "Asia/Shanghai", "messages": [{"role": "user", "content": "明天下午两点开项目会，一个小时"}]})
        repeat = client.post("/api/v1/assistant/chat", json={"client_message_id": "utterance-1",
            "timezone": "Asia/Shanghai", "messages": [{"role": "user", "content": "明天下午两点开项目会，一个小时"}]})
    assert response.status_code == 200
    draft = response.json()["draft"]
    assert draft["status"] == "ready"
    assert draft["candidates"][0]["title"] == "项目会"
    assert SqliteRepository(path).list_events("local") == []
    assert repeat.json()["draft"]["draft_id"] == draft["draft_id"]


def test_assistant_incomplete_event_request_asks_for_clock_time(tmp_path):
    path = tmp_path / "kairos.db"
    model = FixedModel(ModelTurn(None, (rigid_draft_call(),)), ModelTurn("下周二下午具体几点上课？"))
    with TestClient(create_app(str(path), clock=FixedClock(), assistant_task_model=model)) as client:
        response = client.post("/api/v1/assistant/chat", json={"client_message_id": "utterance-2",
            "timezone": "Asia/Shanghai", "messages": [{"role": "user", "content": "下周二下午上课"}]})
    assert response.status_code == 200
    assert response.json()["draft"] is None
    assert "几点" in response.json()["answer"]
    assert SqliteRepository(path).list_events("local") == []


def test_overlap_response_preserves_review_token_and_allows_confirmed_retry(tmp_path):
    client, repo = client_for(tmp_path)
    for index in range(2):
        draft = post_draft(client, '明天下午两点开项目会，一个小时', f'overlap-{index}').json()
        body = {'revision': draft['revision'],
                'confirmed_candidate_ids': [draft['candidates'][0]['candidate_id']],
                'confirmation_digest': draft['confirmation_digest'], 'conflict_acceptance': None}
        url = f"/api/v1/drafts/{draft['draft_id']}/commit"
        headers = {'Idempotency-Key': f'save-overlap-{index}'}
        response = client.post(url, headers=headers, json=body)
        if index == 0:
            assert response.status_code == 200
        else:
            assert response.status_code == 409
            detail = response.json()['detail']
            assert detail['conflict_pairs']
            assert len(repo.list_events('local')) == 1
            body['conflict_acceptance'] = detail['conflict_acceptance']
            assert client.post(url, headers=headers, json=body).status_code == 200
            assert len(repo.list_events('local')) == 2
