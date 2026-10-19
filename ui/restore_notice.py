"""
Post-launch notice for the Station Restore boot step (QA ⚠29, 2026-10-19).

A database restore is never silent any more:
  • applied  → info: what it was restored from, when it was staged, and
                where the previous database was kept (safety copy).
  • refused  → the staged restore was too old or did not match what was
                staged, so the live database was NOT touched. The operator
                chooses "Apply on Next Restart" (re-stamps it) or
                "Don't Apply" (default, Esc / Enter: set aside, nothing lost).
"""

from __future__ import annotations

import logging

from core import dialogs

log = logging.getLogger("RestoreNotice")


def show_restore_notice(parent, status: dict) -> str:
    """Show the notice for ``status`` (core.backup_restore.LAST_RESTORE).
    Returns what happened: 'applied-shown', 'approved', 'declined' or ''."""
    from core import backup_restore as br
    kind = status.get("status")
    src = status.get("source") or "unknown source"
    when = status.get("staged_at") or "unknown time"
    if kind == "applied":
        safety = status.get("safety_copy") or "(no previous database)"
        dialogs.info(
            parent, "Database restored",
            f"The station database was restored from:\n{src}\n"
            f"(staged {when}).\n\n"
            f"Your previous database was kept as:\n{safety}")
        return "applied-shown"
    if kind == "refused":
        reason = status.get("reason") or "it could not be verified"
        approve = dialogs.confirm(
            parent, "Database restore NOT applied",
            f"A database restore from:\n{src}\n(staged {when})\n"
            f"was NOT applied because {reason}.\n\n"
            f"Your current database is unchanged. Apply this restore "
            f"the next time RadioAI starts?",
            yes_label="Apply on Next Restart", no_label="Don't Apply",
            default_no=True)
        if approve and br.approve_pending_restore():
            dialogs.info(parent, "Restore scheduled",
                         "Restart RadioAI to apply the restore.")
            return "approved"
        br.discard_pending_restore()
        return "declined"
    return ""
