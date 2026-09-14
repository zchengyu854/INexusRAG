"""连接池：借出/归还/上限，以及「嵌套借第二条连接不能自死锁」的回归。

不连真实 PostgreSQL：把 psycopg.connect 换成假连接，保证测试离线可跑。
"""
import threading
import types
import unittest
from unittest.mock import patch

from src.storage import database


class _FakeConnection:
    def __init__(self) -> None:
        self.closed = False
        self.info = types.SimpleNamespace(transaction_status=0)

    def close(self) -> None:
        self.closed = True

    def rollback(self) -> None:
        pass


class ConnectionPoolTests(unittest.TestCase):
    def _pool(self, min_size: int = 1, max_size: int = 3):
        created: list[_FakeConnection] = []

        def fake_connect(*_args, **_kwargs):
            conn = _FakeConnection()
            created.append(conn)
            return conn

        patcher = patch.object(database.psycopg, "connect", side_effect=fake_connect)
        patcher.start()
        self.addCleanup(patcher.stop)
        return database._ConnectionPool("dsn", min_size=min_size, max_size=max_size), created

    def test_nested_borrow_does_not_deadlock(self):
        """回归：getconn 曾在持锁状态下调用 _connect，而 _connect 又去抢同一把
        非可重入锁 → 需要第二条连接时永久挂死（并发请求即触发）。

        用看门狗线程 + join 超时，回归时是「断言失败」而不是「测试挂住」。
        """
        pool, created = self._pool(min_size=1, max_size=3)
        done: dict = {}

        def worker():
            try:
                first = pool.getconn()
                second = pool.getconn()
                pool.putconn(first)
                pool.putconn(second)
                done["ok"] = True
            except Exception as exc:  # pragma: no cover - 正常路径不触发
                done["error"] = exc

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        thread.join(timeout=5)
        self.assertTrue(done.get("ok"), "嵌套借连接挂死：连接池出现自死锁回归")
        self.assertEqual(len(created), 2)

    def test_connections_are_reused_after_return(self):
        pool, created = self._pool(min_size=1, max_size=2)
        first = pool.getconn()
        pool.putconn(first)
        self.assertIs(pool.getconn(), first)
        self.assertEqual(len(created), 1)

    def test_pool_never_exceeds_max_size(self):
        pool, created = self._pool(min_size=1, max_size=2)
        pool.getconn()
        pool.getconn()
        self.assertEqual(len(created), 2)

    def test_closed_connection_is_replaced(self):
        pool, created = self._pool(min_size=1, max_size=2)
        conn = pool.getconn()
        conn.closed = True
        pool.putconn(conn)
        replacement = pool.getconn()
        self.assertIsNot(replacement, conn)
        self.assertFalse(replacement.closed)


if __name__ == "__main__":
    unittest.main()
