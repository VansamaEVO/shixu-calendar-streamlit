"""共享访问密码校验；只在服务器内保存登录状态，不把密码传给前端。"""

from collections import deque
from hashlib import sha256
from hmac import compare_digest
from threading import Lock
import time

SESSION_SECONDS = 8 * 60 * 60


def password_fingerprint(password):
    return sha256(password.encode("utf-8")).hexdigest()


def authenticated(state, password, now=None):
    now = time.time() if now is None else now
    return (
        isinstance(state.get("login_until"), (int, float))
        and now < state["login_until"] <= now + SESSION_SECONDS + 1
        and compare_digest(str(state.get("login_fingerprint", "")), password_fingerprint(password))
    )


def sign_out(state):
    for key in list(state):
        # 登出清理历史数据、编辑草稿与命令结果，避免后一位访问者继承。
        if key != "login_attempt_id":
            del state[key]


class LoginGuard:
    """会话限速＋进程级失败预算，不依赖可伪造的客户端 IP。"""

    def __init__(self):
        self.lock = Lock()
        self.failures = deque()
        self.sessions = {}

    def attempt(self, session_id, candidate, expected, state, now=None):
        now = time.time() if now is None else now
        with self.lock:
            while self.failures and self.failures[0] <= now - 600:
                self.failures.popleft()
            for key in list(self.sessions):
                if self.sessions[key][1] <= now:
                    del self.sessions[key]
            count, until = self.sessions.get(session_id, (0, now + 600))
            if count >= 8 or len(self.failures) >= 100:
                return False, "尝试次数较多，请十分钟后再试。"
            correct = isinstance(candidate, str) and compare_digest(candidate.encode("utf-8"), expected.encode("utf-8"))
            if not correct:
                self.failures.append(now)
                if len(self.sessions) >= 2048 and session_id not in self.sessions:
                    self.sessions.pop(next(iter(self.sessions)))
                self.sessions[session_id] = (count + 1, until)
                return False, "访问密码不正确。"
            self.sessions.pop(session_id, None)
        state["login_until"] = now + SESSION_SECONDS
        state["login_fingerprint"] = password_fingerprint(expected)
        return True, ""
