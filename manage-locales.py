#!/usr/bin/env python3
"""A utility for managing project localization files using Babel.

This script provides a command-line interface to perform the following actions:
- extract: Extract translatable strings from the source code into a .pot file.
- update: Update .po files for each language based on the .pot template.
- compile: Compile .po files into binary .mo files.

For help, use the 'help' command. When run without arguments,
all three actions are performed sequentially.
"""

from pathlib import Path
import subprocess
import sys

# --- Configuration: Explicitly define constants ---
PROJECT_NAME = "teamtalk_reg_system"
COPYRIGHT_HOLDER = "kirill-jjj"
LOCALE_DOMAIN = "messages"
BABEL_CONFIG = "babel.cfg"

# --- Paths: Use pathlib for reliability ---
try:
    BASE_DIR = Path(__file__).resolve().parent
    LOCALE_DIR = BASE_DIR / "locales"
    POT_FILE = LOCALE_DIR / f"{LOCALE_DOMAIN}.pot"
except NameError:
    # This fallback might occur if the script is run in an environment
    # where __file__ is not defined (e.g., some forms of exec).
    # Using Path.cwd() as a best guess for BASE_DIR in such cases.
    BASE_DIR = Path.cwd()
    LOCALE_DIR = BASE_DIR / "locales"
    POT_FILE = LOCALE_DIR / f"{LOCALE_DOMAIN}.pot"

def run_command(command: list[str]) -> None:
    """Executes an external command and handles errors. (DRY principle)."""
    print(f"▶️  Executing: {' '.join(command)}")
    try:
        # Explicit and safe subprocess call
        result = subprocess.run(  # noqa: S603
            command,
            check=True,  # Raise an exception on error
            text=True,
            capture_output=True,
            encoding="utf-8",
            cwd=BASE_DIR,  # Ensure commands run from project root
            shell=False,
        )
        # Print stdout if it exists (useful for compile --statistics)
        if result.stdout:
            print(result.stdout.strip())

    except FileNotFoundError:
        # Handle error if Babel is not installed or not in PATH
        print(
            f"❌ Error: Command '{command[0]}' not found.",
            "Ensure that Babel is installed (`pip install Babel`)",
            "and that the path to 'pybabel' is in the PATH environment variable.",
            sep="\n",
            file=sys.stderr,
        )
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        # Detailed error output for easy debugging
        print(
            f"❌ Error: Command finished with exit code {e.returncode}.",
            "--- stderr output: ---",
            e.stderr.strip(),
            "-----------------------",
            sep="\n",
            file=sys.stderr,
        )
        sys.exit(1)

def extract_messages() -> None:
    """Extracts translatable strings into a .pot file."""
    command = [
        "pybabel", "extract",
        "-F", BABEL_CONFIG,
        "-o", str(POT_FILE),
        f"--project={PROJECT_NAME}",
        f"--copyright-holder={COPYRIGHT_HOLDER}",
        "--keywords=_", # Standard keyword for gettext
        "." # Search current directory and subdirectories
    ]
    run_command(command)
    print(f"✅ Messages successfully extracted to '{POT_FILE.relative_to(BASE_DIR)}'")

def update_catalogs() -> None:
    """Updates .po files based on the .pot template."""
    # Ensure LOCALE_DIR exists before trying to update,
    # though Babel might create it for 'init' but not always for 'update'.
    if not LOCALE_DIR.exists():
        print(
            f"ℹ️ Locale directory '{LOCALE_DIR.relative_to(BASE_DIR)}' does not exist. "
            "Skipping update or create it and language subdirectories."
        )
        return

    command = [
        "pybabel", "update",
        "-i", str(POT_FILE),
        "-d", str(LOCALE_DIR),
        "-D", LOCALE_DOMAIN,
        "--update-header-comment", # Update header comment in .po files
        "--previous" # Keep previous msgid lines as comments
    ]
    run_command(command)
    print("✅ Translation catalogs (.po) successfully updated.")

def compile_catalogs() -> None:
    """Compiles .po files into binary .mo files."""
    if not LOCALE_DIR.exists():
        print(
            f"ℹ️ Locale directory '{LOCALE_DIR.relative_to(BASE_DIR)}' does not exist. "
            "Skipping compilation."
        )
        return

    command = [
        "pybabel", "compile",
        "-d", str(LOCALE_DIR),
        "-D", LOCALE_DOMAIN,
        "--statistics" # Show statistics about compiled files
    ]
    run_command(command)
    print("✅ Translation catalogs (.mo) successfully compiled.")

def print_help() -> None:
    """Prints help information on how to use the script."""
    # Use the module's docstring as the source of help (DRY principle)
    print(sys.modules[__name__].__doc__)
    print("Available commands:")
    print("  extract      - Only extract strings to .pot file.")
    print("  update       - Only update .po files.")
    print("  compile      - Only compile .mo files.")
    print("  help         - Show this help message.")
    print("\nWithout arguments - extract, update, and compile are run sequentially.")

def main() -> None:
    """Main function that controls logic based on arguments."""
    actions = {
        "extract": extract_messages,
        "update": update_catalogs,
        "compile": compile_catalogs,
        "help": print_help,
    }

    action_key = sys.argv[1] if len(sys.argv) > 1 else "all"

    if action_key == "all":
        print("--- Starting full localization update cycle ---\n")
        extract_messages()
        update_catalogs()
        compile_catalogs()
        print("\n🎉 All localization steps completed successfully.")
    elif action_key in actions:
        actions[action_key]()
    else:
        print(f"❌ Unknown command: '{action_key}'", file=sys.stderr)
        print("Use the 'help' command for assistance.", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
