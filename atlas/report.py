import json
from pathlib import Path

def web_safe(value):
    """Keep large byte counts exact across JavaScript parse/export cycles."""
    if isinstance(value, int) and not isinstance(value, bool) and abs(value) > 2**53 - 1:
        return str(value)
    if isinstance(value, dict):
        return {key: web_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [web_safe(item) for item in value]
    return value


def html(report=None):
    payload = json.dumps(web_safe(report), ensure_ascii=True).replace('<', '\\u003c')
    page = Path(__file__).with_name('ui.html').read_text().replace('__SNAPSHOT__', payload)
    if report is not None:
        page = page.replace("connect-src 'self'", "connect-src 'none'")
    return page
