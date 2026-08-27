import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

# ===== 配置区（按需修改）=====
BASE_URL = 'http://localhost:8080'
USERNAME = 'admin'
PASSWORD = 'admin123'   # 复现 BUG_LOGIN_001 时改成错误密码，如 'wrong123'
RUNS = 10               # 回归次数

REDIS_CLI_CANDIDATES = [
    r'C:/Program Files/Redis/redis-cli.exe',
    r'C:/Program Files/Redis/redis-cli',
]


def find_redis_cli():
    for p in REDIS_CLI_CANDIDATES:
        if os.path.exists(p):
            return p
    return shutil.which('redis-cli') or 'redis-cli'


REDIS_CLI = find_redis_cli()


def http_json(url, method='GET', data=None):
    body = json.dumps(data).encode('utf-8') if data is not None else None
    req = urllib.request.Request(url, data=body, method=method)
    if body is not None:
        req.add_header('Content-Type', 'application/json')
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode('utf-8'))


def get_captcha(uuid):
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
    return out


def login_once(round_no, password):
    t0 = time.time()

    # 1. 拿验证码 uuid
    cap = http_json(f'{BASE_URL}/captchaImage')
    if cap.get('code') != 200:
        raise RuntimeError(f"captchaImage 失败: {json.dumps(cap, ensure_ascii=False)}")
    uuid = cap['uuid']

    # 2. 读验证码明文
    code = get_captcha(uuid)

    # 3. 登录拿 token
    login = http_json(f'{BASE_URL}/login', 'POST', {
        'username': USERNAME, 'password': password, 'code': code, 'uuid': uuid,
    })

    ms = int((time.time() - t0) * 1000)
    return {
        'round': round_no,
        'ok': login.get('code') == 200 and isinstance(login.get('token'), str),
        'ms': ms,
        'code': login.get('code'),
        'msg': login.get('msg'),
        'has_token': bool(login.get('token')),
    }


def main():
    # 让控制台按 UTF-8 输出，避免 ✓/✗ 在 GBK 下崩溃
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

    runs = int(sys.argv[1]) if len(sys.argv) > 1 else RUNS
    password = sys.argv[2] if len(sys.argv) > 2 else PASSWORD

    print('登录接口自动化回归')
    print(f'  base={BASE_URL}  user={USERNAME}  password={password}  次数={runs}')
    print(f'  redis-cli={REDIS_CLI}\n')

    passed = 0
    failed = 0
    failures = []

    for i in range(1, runs + 1):
        try:
            r = login_once(i, password)
            if r['ok']:
                passed += 1
                print(f"[{i:02d}] ✓ 通过  {r['ms']}ms  code={r['code']}  token={'有' if r['has_token'] else '无'}")
            else:
                failed += 1
                failures.append(r)
                print(f"[{i:02d}] ✗ 失败  {r['ms']}ms  code={r['code']}  msg={r['msg']}")
        except Exception as e:
            failed += 1
            failures.append({'round': i, 'error': str(e)})
            print(f"[{i:02d}] ✗ 异常  {e}")

    print('\n===== 汇总 =====')
    print(f'总数 {runs} | 通过 {passed} | 失败 {failed} | 通过率 {passed / runs * 100:.1f}%')
    if failures:
        print('\n失败明细：')
        for f in failures:
            if 'error' in f:
                print(f"  - 第 {f['round']} 次: {f['error']}")
            else:
                print(f"  - 第 {f['round']} 次: code={f['code']} msg={f['msg']}")


if __name__ == '__main__':
    main()
