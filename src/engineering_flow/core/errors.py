class FlowError(Exception):
    """可供适配层展示的诊断，不将失败解释为成功。"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
