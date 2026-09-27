from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from kairos.adapters.persistence.sqlite import SqliteRepository
from kairos.application.draft_commit import DraftCommitService
from kairos.application.drafts import DraftService
from kairos.application.occurrence_commands import OccurrenceService
from kairos.domain.drafts import Candidate
from kairos.main import create_app


class Clock:
    def __init__(self, instant): self.instant = instant
    def now(self): return self.instant


def test_due_reminder_is_acknowledged_once_and_stays_hidden_after_reload(tmp_path):
    now = datetime(2026, 9, 26, 6, 55, tzinfo=UTC)
    clock = Clock(now)
    db = tmp_path / 'kairos.db'
    repo = SqliteRepository(db)
    draft = DraftService(repo, clock).create('local', [Candidate('class', '软件工程课', '教学楼A', now + timedelta(minutes=5), now + timedelta(minutes=105), 'Asia/Shanghai')], source_message_id='msg')
    DraftCommitService(repo, clock).commit('local', draft.draft_id, draft.revision, ['class'], draft.confirmation_digest, 'commit')

    app = create_app(str(db), clock=clock, owner_id='local')
    with TestClient(app) as client:
        due = client.get('/api/v1/state').json()
        assert len(due['due_reminders']) == 1
        reminder = due['due_reminders'][0]
        assert reminder['occurrence_id']
        assert reminder['event_title'] == '软件工程课'
        assert reminder['location'] == '教学楼A'
        assert reminder['start_at'] == (now + timedelta(minutes=5)).isoformat().replace('+00:00', 'Z')
        assert reminder['minutes_until_start'] == 5
        assert due['next_transition_at'] == reminder['start_at']

        acknowledged = client.post(f"/api/v1/reminders/{reminder['reminder_id']}/ack",
            headers={'Idempotency-Key': 'ack-1'},
            json={'expected_version': reminder['version'], 'schedule_revision': reminder['schedule_revision']})
        assert acknowledged.status_code == 200
        assert acknowledged.json()['acknowledged_at'] == now.isoformat().replace('+00:00', 'Z')
        after_ack = client.get('/api/v1/state').json()
        assert after_ack['due_reminders'] == []
        assert after_ack['next_transition_at'] == reminder['start_at']
        assert client.post(f"/api/v1/reminders/{reminder['reminder_id']}/ack",
            headers={'Idempotency-Key': 'ack-1'},
            json={'expected_version': reminder['version'], 'schedule_revision': reminder['schedule_revision']}).json() == acknowledged.json()


def test_reminder_ack_for_stale_schedule_is_rejected(tmp_path):
    now = datetime(2026, 9, 26, 6, 55, tzinfo=UTC)
    clock = Clock(now)
    db = tmp_path / 'kairos.db'
    repo = SqliteRepository(db)
    draft = DraftService(repo, clock).create('local', [Candidate('class', '课程', None, now + timedelta(minutes=5), now + timedelta(hours=1), 'Asia/Shanghai')], source_message_id='msg')
    DraftCommitService(repo, clock).commit('local', draft.draft_id, draft.revision, ['class'], draft.confirmation_digest, 'commit')
    app = create_app(str(db), clock=clock, owner_id='local')
    with TestClient(app) as client:
        reminder = client.get('/api/v1/state').json()['due_reminders'][0]
        OccurrenceService(repo, clock).reschedule_single('local', reminder['occurrence_id'], reminder['version'],
            now + timedelta(minutes=7), now + timedelta(hours=1, minutes=7))
        result = client.post(f"/api/v1/reminders/{reminder['reminder_id']}/ack",
            headers={'Idempotency-Key': 'stale'},
            json={'expected_version': reminder['version'], 'schedule_revision': reminder['schedule_revision']})
        assert result.status_code == 409
        assert client.get('/api/v1/state').json()['due_reminders'] == []


def test_state_exposes_active_conflict_members_and_non_placeholder_revision(tmp_path):
    now = datetime(2026, 9, 26, 6, 55, tzinfo=UTC)
    clock = Clock(now)
    db = tmp_path / 'kairos.db'
    repo = SqliteRepository(db)
    drafts = DraftService(repo, clock)
    first = drafts.create('local', [Candidate('a', '软件工程课', None, now, now + timedelta(hours=1), 'Asia/Shanghai')], source_message_id='a')
    second = drafts.create('local', [Candidate('b', '项目讨论', None, now + timedelta(hours=2), now + timedelta(hours=3), 'Asia/Shanghai')], source_message_id='b')
    DraftCommitService(repo, clock).commit('local', first.draft_id, first.revision, ['a'], first.confirmation_digest, 'commit-a')
    DraftCommitService(repo, clock).commit('local', second.draft_id, second.revision, ['b'], second.confirmation_digest, 'commit-b')
    b_occurrence = repo.list_occurrences('local', now, now + timedelta(days=1))[1]
    repo.reschedule_single('local', b_occurrence.occurrence_id, b_occurrence.version, now, now + timedelta(hours=1))
    app = create_app(str(db), clock=clock, owner_id='local')

    with TestClient(app) as client:
        state = client.get('/api/v1/state').json()

    assert state['state_revision'] not in (0, 1)
    assert len(state['conflicts']) == 1
    assert set(state['conflicts'][0]['member_ids']) == {item['occurrence_id'] for item in state['active_occurrences']}
    assert state['conflicts'][0]['snapshot_revision'] == state['state_revision']
    assert state['conflicts'][0]['selected_id'] is None
