"""显式加载四个断言案例，避免测试发现数量为零仍返回成功。"""

import argparse
import importlib.util
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


class IdempotencyTests(unittest.TestCase):
    queue_type = None

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="ef-batch-example-")
        self.addCleanup(temporary.cleanup)
        self.database = Path(temporary.name) / "queue.sqlite3"
        self.queue = self.queue_type(self.database)

    def test_retry_returns_original_batch_and_jobs(self):
        original = self.queue.submit("request-1", ["case-a", "case-b"])
        self.assertEqual(self.queue.submit("request-1", ["case-a", "case-b"]), original)
        self.assertEqual(len(original["jobs"]), 2)

    def test_same_request_with_different_cases_is_rejected(self):
        original = self.queue.submit("request-1", ["case-a"])
        with self.assertRaises(ValueError):
            self.queue.submit("request-1", ["case-b"])
        self.assertEqual(self.queue.submit("request-1", ["case-a"]), original)

    def test_reopen_keeps_request_identity(self):
        original = self.queue.submit("request-1", ["case-a"])
        self.queue.submit("request-2", ["case-b"])
        reopened = self.queue_type(self.database)
        self.assertEqual(reopened.submit("request-2", ["case-b"])["batchId"], 2)
        self.assertEqual(reopened.submit("request-1", ["case-a"]), original)

    def test_concurrent_instances_reuse_one_batch(self):
        instances = [self.queue_type(self.database) for _ in range(4)]
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(lambda q: q.submit("request-1", ["case-a", "case-b"]), instances))
        self.assertTrue(all(result == results[0] for result in results))
        # 读取已有批次后再创建新的批次，不能已经额外创建了隐藏的重复批次。
        self.assertEqual(self.queue.submit("request-2", ["case-c"])["batchId"], 2)


def main() -> int:
    parser = argparse.ArgumentParser(description="构造案例的真实重复请求检查")
    parser.add_argument("--implementation", type=Path, default=Path(__file__).with_name("batch_queue.py"))
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("batch_queue_example", args.implementation)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    IdempotencyTests.queue_type = module.BatchQueue
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(IdempotencyTests)
    if suite.countTestCases() != 4:
        raise RuntimeError("构造检查应恰好加载四个案例")
    return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
