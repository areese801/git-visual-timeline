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

    # Validate we're in a git repo
    from git import InvalidGitRepositoryError, Repo

    try:
        repo = Repo(os.getcwd(), search_parent_directories=True)
    except InvalidGitRepositoryError:
        print("Error: not a git repository (or any parent)", file=sys.stderr)
        sys.exit(1)

    # Validate file argument if provided
    if args.file:
        repo_root = repo.working_tree_dir
        file_path = os.path.relpath(os.path.abspath(args.file), repo_root)
        full_path = os.path.join(repo_root, file_path)
        if not os.path.exists(full_path):
            print(f"Error: file not found: {args.file}", file=sys.stderr)
            sys.exit(1)

    from gvt.app import GVTApp

    initial_file = None
    if args.file:
        repo_root = repo.working_tree_dir
        initial_file = os.path.relpath(os.path.abspath(args.file), repo_root)

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
        except Exception:
            pass
        os._exit(128 + signum)

    signal.signal(signal.SIGTERM, _cleanup_terminal)

    app = GVTApp(repo_path=repo.working_tree_dir, initial_file=initial_file)
    app.run()
    # Force exit after app.run() returns — background worker threads may linger
    os._exit(0)
