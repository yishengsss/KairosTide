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
        assert reminder['minutes_until_start'] == 5

        acknowledged = client.post(f"/api/v1/reminders/{reminder['reminder_id']}/ack",
            headers={'Idempotency-Key': 'ack-1'},
            json={'expected_version': reminder['version'], 'schedule_revision': reminder['schedule_revision']})
        assert acknowledged.status_code == 200
        assert acknowledged.json()['acknowledged_at'] == now.isoformat().replace('+00:00', 'Z')
        assert client.get('/api/v1/state').json()['due_reminders'] == []
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
