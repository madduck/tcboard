import logging
import re
from typing import Any, Never
from urllib.parse import quote

from pydantic import BaseModel

logger = logging.getLogger(__name__)


_PARAM_RE = re.compile(r"\{(\w+)(?::[^}]*)?\}")


class APICall(BaseModel):
    method: str
    path: str
    params: dict[str, Any]

    @property
    def interpolated_path(self) -> str:
        def sub(m: re.Match[str]) -> str | Never:
            name = m.group(1)
            if name not in self.params:
                raise KeyError(f"missing path param {name!r} for {self.path}")
            return quote(str(self.params[name]), safe="")

        return _PARAM_RE.sub(sub, self.path)
