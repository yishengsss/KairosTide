import json

from kairos.adapters.ai import mimo


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps({'choices': [{'message': {'content': 'MiMo 已连接'}}]}).encode()


def test_mimo_adapter_posts_openai_compatible_request_without_exposing_key(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured['url'] = request.full_url
        captured['authorization'] = request.get_header('Authorization')
        captured['body'] = json.loads(request.data)
        captured['timeout'] = timeout
        return FakeResponse()

    monkeypatch.setattr(mimo, 'urlopen', fake_urlopen)
    client = mimo.MimoClient('secret-test-token', base_url='https://api.xiaomimimo.com/v1/', model='mimo-v2.6-pro')

    assert client.reply([{'role': 'user', 'content': '你好'}]) == 'MiMo 已连接'
    assert captured['url'] == 'https://api.xiaomimimo.com/v1/chat/completions'
    assert captured['authorization'] == 'Bearer secret-test-token'
    assert captured['body']['model'] == 'mimo-v2.6-pro'
    assert captured['body']['messages'][-1] == {'role': 'user', 'content': '你好'}
    assert 'secret-test-token' not in json.dumps(captured['body'])
