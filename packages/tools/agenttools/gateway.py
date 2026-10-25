"""Route each model call to the local model or the cloud model by what the call would send.

Before every call in the agent loop the gateway computes the level of the outgoing context: the
user's request (sensitivity.label_text) and everything tools returned so far in this turn
(session.data_level, set by the guard). Up to `cloud_max_level` the call may go to the cloud model;
above it the call stays on the local model. A turn can start in the cloud and move to the local
model once a confidential passage or personal data appears; it never moves back within the turn,
because the history already holds that content.

Every decision is recorded (`decisions`) so the audit log shows which backend saw what, and why.
"""
from __future__ import annotations

from . import sensitivity
from .agent import LLMReply
from .core import Session

NO_LOCAL = "（這個請求含有不能送到雲端的資料，但沒有設定地端模型，所以沒有回答）"


class RoutedLLM:
    def __init__(self, local, cloud, session: Session, cloud_max_level: int = sensitivity.INTERNAL,
                 prefer: str = "cloud"):
        self.local, self.cloud, self.session = local, cloud, session
        self.cloud_max_level, self.prefer = cloud_max_level, prefer
        self.decisions: list[dict] = []
        self._pinned_local = False

    def level(self) -> tuple[int, list[str]]:
        req_level, req_reasons = sensitivity.label_text(self.session.request)
        level = max(req_level, self.session.data_level)
        return level, req_reasons + self.session.data_reasons

    def choose(self) -> tuple[str, int, list[str]]:
        level, reasons = self.level()
        if self.cloud is None or (self.prefer == "local" and self.local is not None):
            return "local", level, reasons
        if self._pinned_local or level > self.cloud_max_level:
            self._pinned_local = True
            return "local", level, reasons
        return "cloud", level, reasons

    def chat(self, messages, tools):
        backend, level, reasons = self.choose()
        if backend == "local" and self.local is None:  # cloud-only deployment: refuse rather than send
            reply = LLMReply(NO_LOCAL, [], 0.0)
            backend = "none"
        else:
            reply = (self.cloud if backend == "cloud" else self.local).chat(messages, tools)
        self.decisions.append({"backend": backend, "level": sensitivity.NAMES[level], "reasons": reasons,
                               "usage": reply.usage, "latency_s": round(reply.latency_s, 2)})
        return reply
