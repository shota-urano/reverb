from __future__ import annotations

import uuid


def new_project_id() -> str:
    return "p_" + uuid.uuid4().hex[:16]


def new_job_id() -> str:
    return "j_" + uuid.uuid4().hex[:16]
