"""故意预置缺陷的构造实现：每次重试都创建一批任务，供失败验收使用。"""


class BatchQueue:
    def __init__(self, database):
        self.next_id = 0

    def submit(self, request_id, cases):
        self.next_id += 1
        return {"batchId": self.next_id, "jobs": [{"id": self.next_id * 100 + i, "case": case} for i, case in enumerate(cases)]}
