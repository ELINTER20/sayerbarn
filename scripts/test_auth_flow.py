import urllib.request
import urllib.parse
import http.cookiejar
import random
import string

cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(cj),
    urllib.request.HTTPRedirectHandler()
)


def post(url, data):
    request_data = urllib.parse.urlencode(data).encode('utf-8')
    req = urllib.request.Request(url, data=request_data)
    return opener.open(req)

suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
email = f'test_{suffix}@example.com'
name = 'Test Usuario'
password = 'ClaveSegura123'

print('TEST USER:', email)

try:
    resp = post('http://127.0.0.1:5000/registro', {
        'nombre': name,
        'email': email,
        'password': password,
        'confirmPassword': password,
    })
    print('registro_status', resp.getcode(), resp.geturl())
    if resp.geturl().endswith('/registro'):
        print('registro_failed_body', resp.read(1000).decode('utf-8', errors='ignore'))
    else:
        print('registro_ok redirect to', resp.geturl())

    resp = post('http://127.0.0.1:5000/login', {
        'email': email,
        'password': password,
    })
    print('login_status', resp.getcode(), resp.geturl())
    if resp.geturl().endswith('/login'):
        print('login_failed_body', resp.read(1000).decode('utf-8', errors='ignore'))
    else:
        print('login_ok redirect to', resp.geturl())
except Exception as e:
    print('ERROR', type(e).__name__, e)
