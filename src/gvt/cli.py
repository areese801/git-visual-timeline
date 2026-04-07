"""CLI entry point for gvt."""

import argparse
import os
import sys

from gvt import __version__


def main():
    parser = argparse.ArgumentParser(
        prog="gvt",
        description="Git Visual Timeline — explore file commit history in a TUI",
    )
    parser.add_argument(
        "file",
        nargs="?",
        default=None,
        help="Open directly to this file's timeline",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"gvt {__version__}",
    )

    args = parser.parse_args()

    from git import InvalidGitRepositoryError, Repo

    initial_file = None
    abs_target = os.path.abspath(args.file) if args.file else None

    if abs_target:
        # Determine which repo the target lives in.
        # If the target is a directory, treat it as a repo root (or search up);
        # if it's a file, search from its parent directory.
        search_dir = abs_target if os.path.isdir(abs_target) else os.path.dirname(abs_target)
        try:
            repo = Repo(search_dir, search_parent_directories=True)
        except InvalidGitRepositoryError:
            print(f"Error: {args.file} is not inside a git repository", file=sys.stderr)
            sys.exit(1)

        repo_root = repo.working_tree_dir
        if os.path.isdir(abs_target):
            # Target is a directory (repo root) — open without initial file
            initial_file = None
        else:
            if not os.path.exists(abs_target):
                print(f"Error: file not found: {args.file}", file=sys.stderr)
                sys.exit(1)
            initial_file = os.path.relpath(abs_target, repo_root)
    else:
        # No argument — use cwd's repo
        try:
            repo = Repo(os.getcwd(), search_parent_directories=True)
        except InvalidGitRepositoryError:
            print("Error: not a git repository (or any parent)", file=sys.stderr)
            sys.exit(1)

    from gvt.app import GVTApp

    import signal
    import subprocess

    def _cleanup_terminal(signum, frame):
        """Restore terminal on SIGTERM/SIGINT."""
        try:
            # Restore terminal mode first
            subprocess.run(["stty", "sane"], check=False)
            # Then reset escape sequences
            sys.stdout.write("\033[?1049l")  # exit alternate screen
            sys.stdout.write("\033[?25h")    # show cursor
            sys.stdout.write("\033[0m")      # reset colors
            sys.stdout.write("\033c")        # full terminal reset
            sys.stdout.flush()
        except Exception as e:
            # Signal handler — must never raise. Log best-effort then exit.
            from gvt.logging_setup import get_logger
            get_logger(__name__).warning("terminal cleanup failed: %s", e)
        os._exit(128 + signum)

    signal.signal(signal.SIGTERM, _cleanup_terminal)

    app = GVTApp(repo_path=repo.working_tree_dir, initial_file=initial_file)
    app.run()
    # Force exit after app.run() returns — background worker threads may linger
    os._exit(0)
