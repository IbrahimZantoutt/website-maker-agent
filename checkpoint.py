"""
Git Checkpoint — create/rollback before agent writes.
"""
import subprocess
import re
from typing import Optional


def create_checkpoint(cwd: str, task: str) -> Optional[str]:
    """
    Stage all current files and create a checkpoint commit.
    Returns the commit hash, or None if git is not available.
    """
    try:
        subprocess.run(
            ["git", "add", "-A"],
            cwd=cwd, check=True, capture_output=True,
        )
        msg = f"agent-checkpoint: before task '{task[:60]}'"
        result = subprocess.run(
            ["git", "commit", "-m", msg, "--allow-empty"],
            cwd=cwd, check=True, capture_output=True, text=True,
        )
        # Extract commit hash
        match = re.search(r"\[[\w/-]+\s+([a-f0-9]+)\]", result.stdout)
        if match:
            return match.group(1)
        # Fallback: get HEAD hash
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=cwd, check=True, capture_output=True, text=True,
        )
        return head.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def rollback_to_checkpoint(cwd: str, commit_hash: str) -> bool:
    """
    Hard reset to the checkpoint commit. Returns True on success.
    """
    try:
        subprocess.run(
            ["git", "reset", "--hard", commit_hash],
            cwd=cwd, check=True, capture_output=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
