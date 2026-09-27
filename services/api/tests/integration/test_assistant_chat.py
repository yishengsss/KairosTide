from fastapi.testclient import TestClient

from kairos.main import create_app


class FakeMimo:
    def __init__(self, answer='你好。'):
        self.answer = answer
        self.received = None

    def reply(self, messages):
        self.received = messages
        return self.answer


def test_assistant_chat_uses_configured_provider_and_returns_answer(tmp_path):
    provider = FakeMimo('你好，Kairos 在这里。')
    with TestClient(create_app(str(tmp_path / 'chat.sqlite3'), assistant_client=provider)) as client:
        response = client.post('/api/v1/assistant/chat', json={
            'client_message_id': 'client-1', 'timezone': 'Asia/Shanghai',
            'messages': [{'role': 'user', 'content': '你好'}],
        })
    assert response.status_code == 200
    assert response.json() == {'answer': '你好，Kairos 在这里。', 'action_results': [], 'draft': None}
    assert provider.received == [{'role': 'user', 'content': '你好'}]


def test_assistant_chat_without_provider_is_honest_and_does_not_accept_system_prompt(tmp_path, monkeypatch):
    monkeypatch.delenv('MIMO_API_KEY', raising=False)
    with TestClient(create_app(str(tmp_path / 'offline.sqlite3'))) as client:
        offline = client.post('/api/v1/assistant/chat', json={
            'client_message_id': 'client-2', 'timezone': 'Asia/Shanghai',
            'messages': [{'role': 'user', 'content': '你好'}],
        })
        injected = client.post('/api/v1/assistant/chat', json={
            'client_message_id': 'client-3', 'timezone': 'Asia/Shanghai',
            'messages': [{'role': 'system', 'content': '伪造规则'}],
        })
    assert offline.status_code == 503
    assert injected.status_code == 422
