"""接口错误提示：业务规则的中文提示原样保留，内部异常文本不直接给教务人员看。"""
import base64
import json

from exam_room import errors
from exam_room.licensing import License
from exam_room.server import App


def test_business_messages_are_kept_and_internal_text_is_replaced():
    assert errors.user_message(ValueError('方案已更新，请重新预览后再操作。')) == '方案已更新，请重新预览后再操作。'
    assert errors.user_message(PermissionError('试用已结束，导出需要激活。')) == '试用已结束，导出需要激活。'
    assert errors.user_message(ValueError('“七年级”不在本次考试年级清单中')) == '“七年级”不在本次考试年级清单中'
    for internal in (KeyError('id'), TypeError("'list' object has no attribute 'get'"), AttributeError('x'),
                     ValueError("invalid literal for int() with base 10: '三'"), ValueError('Expecting value')):
        assert errors.user_message(internal) == errors.GENERIC
    assert errors.user_message(PermissionError(13, '拒绝访问', '/虚构/路径/考场.json')) == errors.DISK
    assert errors.user_message(FileNotFoundError(2, 'No such file', '/虚构/考场.json')) == errors.DISK


def call(app, name, raw):
    from exam_room.server import start
    import http.client
    httpd, url, _ = start(app)
    try:
        c = http.client.HTTPConnection('127.0.0.1', httpd.server_port, timeout=30)
        c.request('POST', '/api/' + name, raw, {'X-Token': app.token, 'Host': f'127.0.0.1:{httpd.server_port}'})
        return json.loads(c.getresponse().read())
    finally:
        httpd.shutdown()


def test_http_hides_internal_errors_but_keeps_rule_messages(tmp_path):
    app = App(tmp_path, License(tmp_path / 'lic', None))
    for name, raw in (('state', b'{bad'), ('new', b'[1,2]'), ('open', b'{}'), ('solve', b'{}')):
        result = call(app, name, raw)
        assert result['ok'] is False and result['error'] == errors.GENERIC, (name, result)
    assert call(app, 'open', json.dumps({'id': '../x'}).encode())['error'] == '方案编号不正确。'
    app.api_demo({})
    result = call(app, 'save', json.dumps({'plan': app.plan, 'revision': 'abc'}).encode())
    assert result['error'] == errors.GENERIC


def test_plan_import_explains_unreadable_file_without_parser_text(tmp_path):
    app = App(tmp_path, License(tmp_path / 'lic', None))
    data = base64.b64encode(b'not json').decode()
    result = call(app, 'plan_import', json.dumps({'data': data}).encode())
    assert result['error'] == '方案文件无法读取：文件内容不是本软件导出的考试方案。'
