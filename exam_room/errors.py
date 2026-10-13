"""把内部异常换成教务人员能看懂的中文提示；业务规则本身的中文提示原样保留。"""
import re

GENERIC = '请求内容不完整或格式不正确，请重试。如果反复出现，请先保存方案，再联系软件提供者。'
DISK = '本机文件读写失败，请检查磁盘空间和文件权限后重试。'
_CHINESE = re.compile(r'[一-鿿]')


def is_user_message(error):
    """业务规则抛出的提示：ValueError 等，带中文，且不以英文字母开头（排除 Python 自带的英文报错）。"""
    if isinstance(error, OSError) and error.errno is not None:
        return False
    text = str(error)
    starts_english = text[:1].isascii() and text[:1].isalpha()
    return isinstance(error, (ValueError, PermissionError, RuntimeError)) and bool(_CHINESE.search(text)) \
        and not starts_english


def user_message(error):
    if is_user_message(error):
        return str(error)
    if isinstance(error, OSError) and error.errno is not None:
        return DISK
    return GENERIC
