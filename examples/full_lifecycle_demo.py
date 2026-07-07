"""One-command full lifecycle proof. Runs offline with MockProvider.

Resets the demo state, executes the canonical scripted turns —
remember → retrieve → update → forget → select → explain → compress —
and prints the resulting lifecycle state with explicit assertions
proving that superseded and forgotten memories are excluded from the
final context while updated experience is used.

Run:

    PYTHONPATH=. python examples/full_lifecycle_demo.py

Exits 0 when every lifecycle assertion passes.
"""

import sys

from demo.lifecycle_script import (
    format_lifecycle_demo_report,
    run_full_lifecycle_demo,
)


def main() -> int:
    result = run_full_lifecycle_demo()
    print(format_lifecycle_demo_report(result))
    return 0 if result.all_assertions_passed else 1


if __name__ == "__main__":
    sys.exit(main())
