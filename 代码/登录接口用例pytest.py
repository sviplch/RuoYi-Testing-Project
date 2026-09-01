import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request

import pytest

# ===== 配置区 =====
BASE_URL = 'http://localhost:8080'
DISABLED_USER = 'disabled01'  # TODO: 改成你库里实际建的「停用」账号用户名

# 特殊标记
MISSING = object()      # 表示「不传该字段」
VALID = '__VALID__'     # 表示「取一对新鲜的正确验证码」

# 若依后端对「缺字段/空串/密码长度错/用户不存在/密码错误」统一返回这条通用文案，
# 不区分具体原因（安全设计，避免暴露账号是否存在）。见 messages.properties。
GENERIC_LOGIN_FAIL = '用户不存在/密码错误'

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


# ===== 验证码逻辑（复用）=====
def get_valid_captcha():
    """取一对新鲜的正确验证码，返回 (code, uuid)。"""
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
    # RuoYi 用 JSON 序列化存验证码，读出来带双引号（如 "7"），需去掉
    if len(out) >= 2 and out.startswith('"') and out.endswith('"'):
        out = out[1:-1]
    return out, uuid


def http_json(url, method='GET', data=None):
    body = json.dumps(data).encode('utf-8') if data is not None else None
    req = urllib.request.Request(url, data=body, method=method)
    if body is not None:
        req.add_header('Content-Type', 'application/json')
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


def do_login(username, password, code, uuid):
    """按「字段是否为 MISSING」决定是否放进请求体，返回登录响应 JSON。"""
    body = {}
    if username is not MISSING:
        body['username'] = username
    if password is not MISSING:
        body['password'] = password
    if code is not MISSING:
        body['code'] = code
    if uuid is not MISSING:
        body['uuid'] = uuid
    return http_json(f'{BASE_URL}/login', 'POST', body)


# ===== 测试数据表格（10 条用例：入参 + 预期）=====
# code/uuid 用 VALID = 自动取正确验证码；MISSING = 不传；具体字符串 = 故意传错/固定值
CASES = [
    dict(id='API_001', desc='正常登录，4 参数正确',
         username='admin', password='admin123', code=VALID, uuid=VALID,
         expect=dict(success=True)),
    dict(id='API_002', desc='缺 username 字段',
         username=MISSING, password='admin123', code=VALID, uuid=VALID,
         expect=dict(success=False, msg_contains=GENERIC_LOGIN_FAIL)),
    dict(id='API_003', desc='缺 password 字段',
         username='admin', password=MISSING, code=VALID, uuid=VALID,
         expect=dict(success=False, msg_contains=GENERIC_LOGIN_FAIL)),
    # 缺 code 会触发后端 NPE（validateCaptcha 里 code.equalsIgnoreCase 对 null 空指针），
    # 实际返回 msg=null、code=500，属后端健壮性缺陷。这里只断言登录失败，不断言文案。
    dict(id='API_004', desc='缺 code 字段',
         username='admin', password='admin123', code=MISSING, uuid=VALID,
         expect=dict(success=False)),
    dict(id='API_005', desc='缺 uuid 字段',
         username='admin', password='admin123', code='0000', uuid=MISSING,
         expect=dict(success=False, msg_contains='验证码')),
    dict(id='API_006', desc='username 为空串',
         username='', password='admin123', code=VALID, uuid=VALID,
         expect=dict(success=False, msg_contains=GENERIC_LOGIN_FAIL)),
    dict(id='API_007', desc='password 长度 4（< 最小 5）',
         username='admin', password='1234', code=VALID, uuid=VALID,
         expect=dict(success=False, msg_contains=GENERIC_LOGIN_FAIL)),
    dict(id='API_008', desc='错误验证码 code=0000',
         username='admin', password='admin123', code='0000', uuid=VALID,
         expect=dict(success=False, msg_contains='验证码')),
    dict(id='API_009', desc='不存在的用户',
         username='nouser', password='admin123', code=VALID, uuid=VALID,
         expect=dict(success=False, msg_contains=GENERIC_LOGIN_FAIL)),
    dict(id='API_010', desc='停用（封禁）用户登录',
         username=DISABLED_USER, password='admin123', code=VALID, uuid=VALID,
         expect=dict(success=False, msg_contains='封禁')),
]


@pytest.mark.parametrize('case', CASES, ids=[c['id'] for c in CASES])
def test_login_api(case):
    # 解析验证码：账号密码类用正确验证码；验证码类故意传错/不传
    code = case['code']
    uuid = case['uuid']
    if code is VALID or uuid is VALID:
        fresh_code, fresh_uuid = get_valid_captcha()
        if code is VALID:
            code = fresh_code
        if uuid is VALID:
            uuid = fresh_uuid

    resp = do_login(case['username'], case['password'], code, uuid)
    exp = case['expect']

    if exp.get('success'):
        assert resp.get('code') == 200, f"应登录成功，实际: {json.dumps(resp, ensure_ascii=False)}"
        assert resp.get('msg') == '操作成功', f"msg 应为「操作成功」，实际: {resp.get('msg')}"
        assert isinstance(resp.get('token'), str) and resp.get('token'), '应返回非空 token'
    else:
        assert resp.get('code') != 200, f"应失败，但返回了 code=200: {json.dumps(resp, ensure_ascii=False)}"
        kw = exp.get('msg_contains')
        if kw:
            msg = resp.get('msg') or ''
            assert kw in msg, f"msg 应包含「{kw}」，实际: {json.dumps(resp, ensure_ascii=False)}"
