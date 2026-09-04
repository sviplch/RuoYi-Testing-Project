"""登录会话（token）用例 —— 对应 SOP 02 的 LOGIN_033~037。

覆盖：登录返回 token、token 访问受保护接口、无 token 返回 401、
退出后旧 token 失效、篡改 token 返回 401。
"""
import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request

import pytest

BASE_URL = 'http://localhost:8080'

REDIS_CLI_CANDIDATES = [
    r'C:/Program Files/Redis/redis-cli.exe',
    r'C:/Program Files/Redis/redis-cli',
]


def _find_redis_cli():
    for p in REDIS_CLI_CANDIDATES:
        if os.path.exists(p):
            return p
    return shutil.which('redis-cli') or 'redis-cli'


REDIS_CLI = _find_redis_cli()


def http_json(url, method='GET', data=None, headers=None):
    body = json.dumps(data).encode('utf-8') if data is not None else None
    req = urllib.request.Request(url, data=body, method=method)
    if body is not None:
        req.add_header('Content-Type', 'application/json')
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        raw = e.read().decode('utf-8', errors='replace')
        try:
            return json.loads(raw)
        except Exception:
            return {'code': e.code, 'msg': raw}
    except urllib.error.URLError as e:
        raise RuntimeError(f'请求失败（后端没起？）: {e}') from e


def get_valid_captcha():
    cap = http_json(f'{BASE_URL}/captchaImage')
    if cap.get('code') != 200:
        raise RuntimeError(f"captchaImage 失败: {json.dumps(cap, ensure_ascii=False)}")
    uuid = cap['uuid']
    key = f'captcha_codes:{uuid}'
    out = subprocess.run(
        [REDIS_CLI, 'get', key],
        capture_output=True, text=True, timeout=5,
    ).stdout.strip()
    if not out or out == '(nil)':
        raise RuntimeError(f'验证码不存在或已过期 (key={key})')
    if len(out) >= 2 and out.startswith('"') and out.endswith('"'):
        out = out[1:-1]
    return out, uuid


def login_get_token(username='admin', password='admin123'):
    code, uuid = get_valid_captcha()
    resp = http_json(f'{BASE_URL}/login', 'POST', {
        'username': username, 'password': password, 'code': code, 'uuid': uuid,
    })
    assert resp.get('code') == 200, f"登录失败: {json.dumps(resp, ensure_ascii=False)}"
    return resp['token']


def auth(token):
    return {'Authorization': f'Bearer {token}'}


def test_login_returns_token():
    """LOGIN_033 登录成功返回非空 token"""
    token = login_get_token()
    assert isinstance(token, str) and token


def test_token_access_getInfo():
    """LOGIN_034 带 token 可访问受保护接口 /getInfo"""
    token = login_get_token()
    resp = http_json(f'{BASE_URL}/getInfo', headers=auth(token))
    assert resp.get('code') == 200, f"带 token 访问 /getInfo 应成功: {json.dumps(resp, ensure_ascii=False)}"
    assert 'user' in resp


def test_no_token_access_getInfo():
    """LOGIN_035 无 token 访问 /getInfo 返回 401"""
    resp = http_json(f'{BASE_URL}/getInfo')
    assert resp.get('code') == 401, f"应返回 401: {json.dumps(resp, ensure_ascii=False)}"
    assert '认证失败' in (resp.get('msg') or '')


def test_logout_invalidates_token():
    """LOGIN_036 退出登录后旧 token 失效（返回 401）"""
    token = login_get_token()
    logout = http_json(f'{BASE_URL}/logout', 'POST', headers=auth(token))
    assert logout.get('code') == 200, f"退出应成功: {json.dumps(logout, ensure_ascii=False)}"
    resp = http_json(f'{BASE_URL}/getInfo', headers=auth(token))
    assert resp.get('code') == 401, f"退出后旧 token 应失效: {json.dumps(resp, ensure_ascii=False)}"


def test_tampered_token_401():
    """LOGIN_037 篡改 token 后访问受保护接口返回 401"""
    token = login_get_token()
    mid = len(token) // 2
    tampered = token[:mid] + ('0' if token[mid] != '0' else '1') + token[mid + 1:]
    resp = http_json(f'{BASE_URL}/getInfo', headers=auth(tampered))
    assert resp.get('code') == 401, f"篡改 token 应返回 401: {json.dumps(resp, ensure_ascii=False)}"
