"""用户管理用例 —— 对应 SOP 03 的核心 CRUD + 真实 Bug 复现。

覆盖：查询、新增（含手机号字母 Bug、空昵称）、修改、删除（逻辑删除 +
关联表清理）、重置密码、状态切换、admin 保护、越权（未登录/伪造 token）。
所有落库断言都连 MySQL 做 SQL 核对。
"""
import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request

import pymysql
import pytest

BASE_URL = 'http://localhost:8080'

DB_CONFIG = dict(
    host='127.0.0.1', port=3306, user='root', password='123456',
    database='ry_vue', charset='utf8mb4',
)

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


# ---------------------------------------------------------------- HTTP 层

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


# ---------------------------------------------------------------- 数据库层

def db_query(sql, params=None):
    conn = pymysql.connect(**DB_CONFIG)
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute(sql, params or ())
            return cur.fetchall()
    finally:
        conn.close()


def db_execute(sql, params=None):
    conn = pymysql.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
        conn.commit()
    finally:
        conn.close()


def get_user_id(username, del_flag='0'):
    rows = db_query(
        "SELECT user_id FROM sys_user WHERE user_name=%s AND del_flag=%s",
        (username, del_flag),
    )
    return rows[0]['user_id'] if rows else None


def physical_delete_user(username):
    """物理删除测试用户及其关联（区别于业务上的逻辑删除），保证用例可重复跑。"""
    uid = get_user_id(username, del_flag='0') or get_user_id(username, del_flag='2')
    if uid is None:
        return
    db_execute("DELETE FROM sys_user_role WHERE user_id=%s", (uid,))
    db_execute("DELETE FROM sys_user_post WHERE user_id=%s", (uid,))
    db_execute("DELETE FROM sys_user WHERE user_id=%s", (uid,))


# ---------------------------------------------------------------- 业务层

def add_user(token, username, nick_name='测试用户', dept_id=103,
             password='12345', phone=None, email=None):
    body = {
        'userName': username,
        'nickName': nick_name,
        'deptId': dept_id,
        'password': password,
    }
    if phone is not None:
        body['phonenumber'] = phone
    if email is not None:
        body['email'] = email
    return http_json(f'{BASE_URL}/system/user', 'POST', body, headers=auth(token))


@pytest.fixture(scope='session')
def admin_token():
    return login_get_token()


# ---------------------------------------------------------------- 查询

def test_user_list_default(admin_token):
    """USER_001 默认查询返回用户列表（分页）"""
    resp = http_json(f'{BASE_URL}/system/user/list', headers=auth(admin_token))
    assert resp.get('code') == 200, f"列表应成功: {json.dumps(resp, ensure_ascii=False)}"
    assert 'rows' in resp and 'total' in resp
    assert resp['total'] > 0


def test_user_list_by_username(admin_token):
    """USER_002 按用户名查询 admin（模糊匹配）"""
    resp = http_json(f'{BASE_URL}/system/user/list?userName=admin', headers=auth(admin_token))
    assert resp.get('code') == 200
    names = [r.get('userName') for r in resp.get('rows', [])]
    assert 'admin' in names, f"查询结果应含 admin: {names}"


# ---------------------------------------------------------------- 新增

def test_user_add_success(admin_token):
    """USER_013 正常新增用户，密码落库为 BCrypt 密文"""
    username = 'test_user_add'
    physical_delete_user(username)
    try:
        resp = add_user(admin_token, username, nick_name='新增测试', phone='13800000001')
        assert resp.get('code') == 200, f"新增应成功: {json.dumps(resp, ensure_ascii=False)}"
        row = db_query(
            "SELECT nick_name, LEFT(password,7) AS pwd_prefix, del_flag FROM sys_user WHERE user_name=%s",
            (username,),
        )
        assert row, '新增后应能在库中查到'
        assert row[0]['pwd_prefix'] == '$2a$10$', f"密码应为 BCrypt 密文: {row[0]['pwd_prefix']}"
        assert row[0]['del_flag'] == '0'
    finally:
        physical_delete_user(username)


def test_user_add_empty_username(admin_token):
    """USER_014 用户名为空被 @NotBlank 拦截"""
    resp = http_json(f'{BASE_URL}/system/user', 'POST', {
        'nickName': 'x', 'deptId': 103, 'password': '12345',
    }, headers=auth(admin_token))
    assert resp.get('code') == 500
    assert resp.get('msg') == '用户账号不能为空', f"实际: {resp.get('msg')}"


def test_user_add_duplicate_username(admin_token):
    """USER_015 用户名重复（admin）返回登录账号已存在"""
    resp = add_user(admin_token, 'admin', nick_name='x')
    assert resp.get('code') == 500
    assert '登录账号已存在' in (resp.get('msg') or ''), f"实际: {resp.get('msg')}"


def test_user_add_username_too_long(admin_token):
    """USER_016 用户名 31 位超长被拦截"""
    resp = add_user(admin_token, 'a' * 31, nick_name='x')
    assert resp.get('code') == 500
    assert resp.get('msg') == '用户账号长度不能超过30个字符', f"实际: {resp.get('msg')}"


def test_user_add_phone_letters(admin_token):
    """USER_023【Bug】手机号输 11 位字母仍能保存成功（phonenumber 无 @Pattern）"""
    username = 'test_phone_letters'
    physical_delete_user(username)
    try:
        resp = add_user(admin_token, username, nick_name='手机号字母', phone='abcdefghijk')
        assert resp.get('code') == 200, f"【Bug 复现】应能保存成功: {json.dumps(resp, ensure_ascii=False)}"
        row = db_query("SELECT phonenumber FROM sys_user WHERE user_name=%s", (username,))
        assert row and row[0]['phonenumber'] == 'abcdefghijk', '库中 phonenumber 应为字母'
    finally:
        physical_delete_user(username)


def test_user_add_invalid_email(admin_token):
    """USER_026 邮箱格式错误被 @Email 拦截"""
    resp = add_user(admin_token, 'test_email_invalid', nick_name='x', email='abc')
    assert resp.get('code') == 500
    assert resp.get('msg') == '邮箱格式不正确', f"实际: {resp.get('msg')}"


@pytest.mark.parametrize('nickname', [None, ''])
def test_user_add_empty_nickname(admin_token, nickname):
    """USER_021【Bug】昵称为 null 或空串 → 500：实体无 @NotBlank 且 insertUser 空值过滤导致 nick_name 缺失"""
    body = {'userName': 'test_nick_empty', 'deptId': 103, 'password': '12345'}
    if nickname is not None:
        body['nickName'] = nickname
    resp = http_json(f'{BASE_URL}/system/user', 'POST', body, headers=auth(admin_token))
    assert resp.get('code') == 500
    assert 'nick_name' in (resp.get('msg') or ''), \
        f"应暴露 nick_name 字段错误: {(resp.get('msg') or '')[:120]}"


# ---------------------------------------------------------------- 修改

def test_user_edit_nickname(admin_token):
    """USER_031 修改昵称成功，库中 nick_name 更新"""
    username = 'test_user_edit'
    physical_delete_user(username)
    try:
        assert add_user(admin_token, username, nick_name='旧昵称').get('code') == 200
        uid = get_user_id(username)
        resp = http_json(f'{BASE_URL}/system/user', 'PUT', {
            'userId': uid, 'userName': username, 'nickName': '新昵称', 'deptId': 103,
        }, headers=auth(admin_token))
        assert resp.get('code') == 200, f"修改应成功: {json.dumps(resp, ensure_ascii=False)}"
        row = db_query("SELECT nick_name FROM sys_user WHERE user_name=%s", (username,))
        assert row[0]['nick_name'] == '新昵称'
    finally:
        physical_delete_user(username)


def test_user_edit_admin_forbidden(admin_token):
    """USER_035 修改 admin 被拒绝"""
    resp = http_json(f'{BASE_URL}/system/user', 'PUT', {
        'userId': 1, 'userName': 'admin', 'nickName': 'hacker', 'deptId': 103,
    }, headers=auth(admin_token))
    assert resp.get('code') == 500
    assert resp.get('msg') == '不允许操作超级管理员用户', f"实际: {resp.get('msg')}"


# ---------------------------------------------------------------- 删除

def test_user_delete_logical(admin_token):
    """USER_043/044 删除是逻辑删除：del_flag 变 2，数据仍在库中"""
    username = 'test_user_del'
    physical_delete_user(username)
    try:
        assert add_user(admin_token, username).get('code') == 200
        uid = get_user_id(username)
        resp = http_json(f'{BASE_URL}/system/user/{uid}', 'DELETE', headers=auth(admin_token))
        assert resp.get('code') == 200, f"删除应成功: {json.dumps(resp, ensure_ascii=False)}"
        # 普通查询查不到（过滤 del_flag=2）
        assert get_user_id(username, del_flag='0') is None
        # 逻辑删除后数据还在，del_flag=2
        row = db_query(
            "SELECT user_id, del_flag FROM sys_user WHERE user_name=%s AND del_flag='2'",
            (username,),
        )
        assert row, '逻辑删除后记录物理上仍存在'
        assert row[0]['del_flag'] == '2'
    finally:
        physical_delete_user(username)


def test_user_delete_cleans_role_link(admin_token):
    """删除用户后 sys_user_role 关联表被物理清理（正确行为，非 Bug）"""
    username = 'test_user_role'
    physical_delete_user(username)
    try:
        assert add_user(admin_token, username).get('code') == 200
        uid = get_user_id(username)
        # 给用户分配一个普通角色
        role = db_query("SELECT role_id FROM sys_role WHERE role_key='common' LIMIT 1")
        assert role, '应存在 common 普通角色'
        role_id = role[0]['role_id']
        db_execute("INSERT INTO sys_user_role(user_id, role_id) VALUES(%s, %s)", (uid, role_id))
        assert db_query("SELECT * FROM sys_user_role WHERE user_id=%s", (uid,)), '前置：关联应存在'
        # 删除用户
        resp = http_json(f'{BASE_URL}/system/user/{uid}', 'DELETE', headers=auth(admin_token))
        assert resp.get('code') == 200
        leftover = db_query("SELECT * FROM sys_user_role WHERE user_id=%s", (uid,))
        assert not leftover, f'删除后关联表应被清理，不应残留: {leftover}'
    finally:
        physical_delete_user(username)


def test_user_delete_admin_forbidden(admin_token):
    """USER_048 删除 admin（=当前登录用户）被拒：remove 先判「当前用户不能删除」"""
    resp = http_json(f'{BASE_URL}/system/user/1', 'DELETE', headers=auth(admin_token))
    assert resp.get('code') == 500
    assert resp.get('msg') == '当前用户不能删除', f"实际: {resp.get('msg')}"


# ---------------------------------------------------------------- 重置密码

def test_user_reset_pwd(admin_token):
    """USER_053 重置密码成功，新密码为 BCrypt 密文"""
    username = 'test_user_reset'
    physical_delete_user(username)
    try:
        assert add_user(admin_token, username, password='12345').get('code') == 200
        uid = get_user_id(username)
        resp = http_json(f'{BASE_URL}/system/user/resetPwd', 'PUT', {
            'userId': uid, 'password': 'newpass123',
        }, headers=auth(admin_token))
        assert resp.get('code') == 200, f"重置应成功: {json.dumps(resp, ensure_ascii=False)}"
        row = db_query("SELECT LEFT(password,7) AS pwd_prefix FROM sys_user WHERE user_name=%s", (username,))
        assert row[0]['pwd_prefix'] == '$2a$10$'
    finally:
        physical_delete_user(username)


def test_user_reset_pwd_admin_forbidden(admin_token):
    """USER_057 重置 admin 密码被拒绝"""
    resp = http_json(f'{BASE_URL}/system/user/resetPwd', 'PUT', {
        'userId': 1, 'password': 'hack123',
    }, headers=auth(admin_token))
    assert resp.get('code') == 500
    assert resp.get('msg') == '不允许操作超级管理员用户', f"实际: {resp.get('msg')}"


# ---------------------------------------------------------------- 状态切换

def test_user_change_status(admin_token):
    """USER_060 停用用户，status 变 1"""
    username = 'test_user_status'
    physical_delete_user(username)
    try:
        assert add_user(admin_token, username).get('code') == 200
        uid = get_user_id(username)
        resp = http_json(f'{BASE_URL}/system/user/changeStatus', 'PUT', {
            'userId': uid, 'status': '1',
        }, headers=auth(admin_token))
        assert resp.get('code') == 200, f"停用应成功: {json.dumps(resp, ensure_ascii=False)}"
        row = db_query("SELECT status FROM sys_user WHERE user_name=%s", (username,))
        assert row[0]['status'] == '1'
    finally:
        physical_delete_user(username)


def test_user_change_status_admin_forbidden(admin_token):
    """USER_063 停用 admin 被拒绝"""
    resp = http_json(f'{BASE_URL}/system/user/changeStatus', 'PUT', {
        'userId': 1, 'status': '1',
    }, headers=auth(admin_token))
    assert resp.get('code') == 500
    assert resp.get('msg') == '不允许操作超级管理员用户', f"实际: {resp.get('msg')}"


# ---------------------------------------------------------------- 越权

def test_user_list_no_token():
    """USER_084 未登录调用列表接口返回 401"""
    resp = http_json(f'{BASE_URL}/system/user/list')
    assert resp.get('code') == 401, f"未登录应返回 401: {json.dumps(resp, ensure_ascii=False)}"


def test_user_list_tampered_token(admin_token):
    """USER_085 伪造 token 调用列表接口返回 401"""
    token = admin_token
    mid = len(token) // 2
    tampered = token[:mid] + ('0' if token[mid] != '0' else '1') + token[mid + 1:]
    resp = http_json(f'{BASE_URL}/system/user/list', headers=auth(tampered))
    assert resp.get('code') == 401, f"伪造 token 应返回 401: {json.dumps(resp, ensure_ascii=False)}"
