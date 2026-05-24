import sys
import inspect
import asyncio
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def pytest_configure(config):
    """注册 asyncio marker，避免未安装 pytest-asyncio 时出现 UnknownMarkWarning。"""
    config.addinivalue_line("markers", "asyncio: 异步测试标记（兼容无 pytest-asyncio 环境）")


def pytest_pyfunc_call(pyfuncitem):
    """在未安装 pytest-asyncio 时，兜底执行 async 测试函数。"""
    test_func = pyfuncitem.obj
    if not inspect.iscoroutinefunction(test_func):
        return None
    funcargs = {name: pyfuncitem.funcargs[name] for name in pyfuncitem._fixtureinfo.argnames}
    asyncio.run(test_func(**funcargs))
    return True
