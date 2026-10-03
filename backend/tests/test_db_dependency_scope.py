import re
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"


def test_get_db_is_always_injected_with_function_scope():
    """Default-scope yield dependencies commit after the response is sent (read-your-writes race)."""
    offenders = [
        f"{path.relative_to(APP)}:{lineno}"
        for path in APP.rglob("*.py")
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if re.search(r"Depends\(\s*get_db\s*\)", line)
    ]
    assert not offenders, f'use Depends(get_db, scope="function"): {offenders}'
