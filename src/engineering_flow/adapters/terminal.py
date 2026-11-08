"""本地操作者的交互入口；拒绝管道、--yes 或自报身份作为确认。"""

import json
import os
import pwd
import secrets
import sys

from engineering_flow.core.errors import FlowError
from engineering_flow.core.feedback import ConfirmationPort, ConsentReceipt


class TerminalConfirmation(ConfirmationPort):
    def request(self, opinion: dict) -> ConsentReceipt:
        if not sys.stdin.isatty():
            raise FlowError("confirmation_source", "请由操作者在本地交互终端运行 review confirm；不接受管道或非交互输入。")
        try:
            with open("/dev/tty", "r", encoding="utf-8") as reader, open("/dev/tty", "w", encoding="utf-8", buffering=1) as terminal:
                if not terminal.isatty():
                    raise OSError("不是控制终端")
                challenge = "CONFIRM " + secrets.token_hex(4)
                # JSON 转义所有控制字符，防止意见内容向终端注入控制序列或隐藏提示。
                payload = {k: opinion[k] for k in ("id", "taskId", "reviewId", "snapshotId", "taskRevision", "scope", "decision", "comment")}
                terminal.write("\nEngineering Flow · 本地评审确认\n" + json.dumps(payload, ensure_ascii=True, indent=2) + "\n")
                terminal.write("确认仅覆盖上述范围，不替代必需检查。若不同意请按 Enter 或 Ctrl-C。\n输入 " + challenge + " 以记录本机终端确认：\n")
                answer = reader.readline(256).rstrip("\r\n")
                if answer != challenge:
                    raise FlowError("confirmation_cancelled", "未收到匹配的显式交互，未保存确认。")
                actor = {"source": "interactive_terminal", "uid": os.getuid(), "account": pwd.getpwuid(os.getuid()).pw_name,
                         "tty": os.ttyname(sys.stdin.fileno()), "assurance": "local_session_not_identity_verified"}
                return ConsentReceipt(opinion["integrity"], actor)
        except (OSError, KeyboardInterrupt) as exc:
            raise FlowError("confirmation_cancelled", "交互取消或控制终端不可用，未保存确认。") from exc
