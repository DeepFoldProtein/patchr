"""HTTP Basic auth for the dashboard pages and geo/IP data. Credentials come from
env (PATCHR_DASHBOARD_USER / PATCHR_DASHBOARD_PASSWORD); if no password is set,
auth is disabled and the dashboard stays open. The public prediction API is never
gated by this."""

import logging
import os
import secrets as _secrets
from typing import Optional

from fastapi import Depends, HTTPException
from fastapi.security import HTTPBasic, HTTPBasicCredentials

_DASH_USER = os.environ.get("PATCHR_DASHBOARD_USER", "admin")
_DASH_PASS = os.environ.get("PATCHR_DASHBOARD_PASSWORD", "")
_dash_basic = HTTPBasic(auto_error=False)

if not _DASH_PASS:
    logging.getLogger(__name__).warning(
        "PATCHR_DASHBOARD_PASSWORD not set — /dashboard and geo/IP data are PUBLIC.")


def require_dashboard_auth(
    credentials: Optional[HTTPBasicCredentials] = Depends(_dash_basic),
) -> None:
    if not _DASH_PASS:
        return  # auth disabled — no password configured
    ok = credentials is not None and (
        _secrets.compare_digest(credentials.username, _DASH_USER)
        and _secrets.compare_digest(credentials.password, _DASH_PASS)
    )
    if not ok:
        raise HTTPException(
            status_code=401,
            detail="Dashboard login required",
            headers={"WWW-Authenticate": 'Basic realm="patchr dashboard"'},
        )
