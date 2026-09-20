"""Hand-written tickets used when the LLM is unavailable, and always for onboarding."""

from __future__ import annotations

import copy
from string import Template

from boss.config import Config
from boss.tracks import Level

ONBOARDING_BRIEF = """\
You start today. I am $boss_name, $boss_title at $company_name, and you report to me.

Nobody at a client sees a line of yours until I have seen that your machine works and
that you can hand work in without drama. That is this ticket. One function. It is an
evening's work, not a week's.

In this order:

1. Terminal, this folder, `uv sync`. It creates `.venv` and installs pytest and ruff.
   `git status`: if `.venv` shows up, stop and tell me, do not guess.
2. `uv run pytest -q`. Two tests fail. Read the last three lines before you touch
   anything. I will ask what they said.
3. `src/hello.py`: make `greeting` return the sentence the tests want. Green, then
   `uv run ruff check .`, then fix what it says.
4. Commit with a message that states what you did, not "fix". Then create a file `.env`
   with one junk line, run `git status` again, confirm git does not list it.

Hand in with `boss submit $ticket_id -m "..."`. The message states, one line each: what
the traceback said in step 2, and the one thing that confused you. "Nothing" is not an
answer I accept from someone on day one.

$boss_first
"""

ONBOARDING_FILES = {
    "README.md": (
        "# $company_name sandbox\n\n"
        "One folder per ticket. `TICKET.md` is the brief, `src/` is yours, `tests/` is mine.\n"
        "`uv sync` once, then `uv run pytest -q` as often as you like.\n"
    ),
    "src/hello.py": (
        '"""Your first module here. One function. Make the tests pass, then commit."""\n\n\n'
        "def greeting(name: str) -> str:\n"
        '    """Return the sentence tests/test_hello.py expects."""\n'
        "    raise NotImplementedError\n"
    ),
    "tests/test_hello.py": (
        "from hello import greeting\n\n\n"
        "def test_greeting_names_the_person():\n"
        '    expected = "Hello $engineer_name, welcome to $company_name."\n'
        '    assert greeting("$engineer_name") == expected\n\n\n'
        "def test_greeting_works_for_anyone():\n"
        '    assert greeting("$boss_first").startswith("Hello $boss_first,")\n'
    ),
    ".env.example": (
        "# Nothing secret yet. This file shows the shape; the real .env stays out of git.\n"
        "EXAMPLE_API_KEY=\n"
    ),
}

LABELS_BRIEF = """\
Kvernbit Bakery. Anne-Lise, the owner, prints shelf labels by hand every morning and gets
the member discount wrong about once a week. A wrong label is a customer arguing at the
till. We are fixing that, and this is the first piece: three small functions that turn a
price into what goes on the label.

Open `src/labels.py`. The stub tells you what each function takes and returns; my tests in
`tests/test_labels.py` call them directly. Change a name and you fail before I read a line.

What they do, in plain words. `price_with_discount` takes a price and a percentage and
returns the reduced price, rounded to two decimals. `price_band` says whether a price is
"budget" (under 3), "standard" (3 up to but not including 8) or "premium" (8 and above).
`shelf_label` builds the text on the label: the product name in capitals, a colon, the
price with exactly two decimals, and the word MEMBER at the end when the discount applied.

Rules: no loops, no lists, no files, no input() and no print() inside these functions.
Each one takes values and returns a value. Work three examples out on paper before you
type; if your code and the tests disagree, the paper decides who is wrong.

$boss_first
"""

LABELS_FILES = {
    "src/labels.py": (
        '"""Shelf labels for Kvernbit Bakery: three small pure functions."""\n\n\n'
        "def price_with_discount(price: float, percent: float) -> float:\n"
        '    """The price after taking percent off, rounded to two decimals."""\n'
        "    raise NotImplementedError\n\n\n"
        "def price_band(price: float) -> str:\n"
        '    """"budget" under 3, "standard" from 3 up to (not including) 8, else "premium"."""\n'
        "    raise NotImplementedError\n\n\n"
        "def shelf_label(name: str, price: float, member: bool) -> str:\n"
        '    """Label text. See tests/test_labels.py for the exact shape."""\n'
        "    raise NotImplementedError\n"
    ),
    "tests/test_labels.py": (
        "import pytest\n\n"
        "from labels import price_band, price_with_discount, shelf_label\n\n\n"
        "def test_ten_percent_off():\n"
        "    assert price_with_discount(5.00, 10) == pytest.approx(4.50)\n\n\n"
        "def test_discount_rounds_to_two_decimals():\n"
        "    assert price_with_discount(3.35, 15) == pytest.approx(2.85)\n\n\n"
        "def test_zero_percent_changes_nothing():\n"
        "    assert price_with_discount(7.25, 0) == pytest.approx(7.25)\n\n\n"
        "@pytest.mark.parametrize(\n"
        '    ("price", "band"),\n'
        '    [(1.50, "budget"), (2.99, "budget"), (3.00, "standard"), (7.99, "standard"),\n'
        '     (8.00, "premium"), (24.00, "premium")],\n'
        ")\n"
        "def test_price_band_edges(price, band):\n"
        "    assert price_band(price) == band\n\n\n"
        "def test_label_without_member_price():\n"
        '    assert shelf_label("cinnamon bun", 3.5, False) == "CINNAMON BUN: 3.50"\n\n\n'
        "def test_label_with_member_price():\n"
        '    assert shelf_label("rye loaf", 5.8, True) == "RYE LOAF: 5.80 MEMBER"\n'
    ),
}

SALES_CSV = """\
shop,product,qty,unit_price
Central,Cinnamon bun,42,35.00
Central,Rye loaf,18,58.00
Central,Custard bun,25,38.00
Harbour,Cinnamon bun,31,35.00
Harbour,Rye loaf,22,58.00
Harbour,Coffee,57,29.00
Central,Coffee,63,29.00
Harbour,Custard bun,9,38.00
"""

SALES_BRIEF = """\
Kvernbit Bakery. Two shops, one owner, Anne-Lise, who reconciles Friday sales by hand and
pays us to stop doing that. Their till exports one CSV a day: shop, product, qty,
unit_price. She types one command and reads the day's numbers. That is the job. It is
paid, so it is right to the cent or it is not delivered.

Build `src/sales_summary.py` so that `uv run python src/sales_summary.py data/sales_2026-09-01.csv`
prints total revenue, revenue per shop, and the three best-selling products by quantity.
The function contracts are in the stub. My tests call them directly. Change a name or a
return type and you fail the ticket before I read a line.

Rules: standard library only (`csv`, `pathlib`, `sys`). Read the file once. A missing
file prints one sentence containing "not found" and exits with status 1; a traceback in
front of a client is not something we ship. Money prints with two decimals and " EUR".

Work the expected numbers out on paper from the CSV first. If your code and the tests
disagree, the paper decides who is wrong.

$boss_first
"""

SALES_FILES = {
    "data/sales_2026-09-01.csv": SALES_CSV,
    "src/sales_summary.py": (
        '"""Daily sales summary for Kvernbit Bakery.\n\n'
        "Usage: python src/sales_summary.py data/sales_2026-09-01.csv\n"
        '"""\n\n'
        "import csv\n"
        "import sys\n"
        "from pathlib import Path\n\n\n"
        "def load_sales(path: Path) -> list[dict]:\n"
        '    """Read the CSV into a list of dicts. qty becomes int, unit_price becomes float."""\n'
        "    raise NotImplementedError\n\n\n"
        "def total_revenue(rows: list[dict]) -> float:\n"
        '    """Sum of qty * unit_price over all rows."""\n'
        "    raise NotImplementedError\n\n\n"
        "def revenue_by_shop(rows: list[dict]) -> dict[str, float]:\n"
        '    """Revenue per shop, keyed by shop name."""\n'
        "    raise NotImplementedError\n\n\n"
        "def top_products(rows: list[dict], n: int = 3) -> list[tuple[str, int]]:\n"
        '    """The n products with the highest total qty, best first, as (product, qty)."""\n'
        "    raise NotImplementedError\n\n\n"
        "def format_report(rows: list[dict]) -> str:\n"
        '    """The text the owner reads. See tests/test_sales_summary.py for the exact lines."""\n'
        "    raise NotImplementedError\n\n\n"
        "def main(argv: list[str]) -> int:\n"
        '    """argv[1] is the CSV path. Print the report and return 0, or print a one-line\n'
        '    message containing "not found" and return 1 when the file is missing."""\n'
        "    raise NotImplementedError\n\n\n"
        'if __name__ == "__main__":\n'
        "    sys.exit(main(sys.argv))\n"
    ),
    "tests/test_sales_summary.py": (
        "from pathlib import Path\n\n"
        "import pytest\n\n"
        "from sales_summary import (\n"
        "    format_report,\n"
        "    load_sales,\n"
        "    main,\n"
        "    revenue_by_shop,\n"
        "    top_products,\n"
        "    total_revenue,\n"
        ")\n\n"
        'DATA = Path(__file__).resolve().parent.parent / "data" / "sales_2026-09-01.csv"\n\n\n'
        "@pytest.fixture\n"
        "def rows():\n"
        "    return load_sales(DATA)\n\n\n"
        "def test_load_gives_eight_typed_rows(rows):\n"
        "    assert len(rows) == 8\n"
        '    assert rows[0]["shop"] == "Central"\n'
        '    assert rows[0]["qty"] == 42 and isinstance(rows[0]["qty"], int)\n'
        '    assert rows[0]["unit_price"] == 35.0\n'
        '    assert isinstance(rows[0]["unit_price"], float)\n\n\n'
        "def test_total_revenue(rows):\n"
        "    assert total_revenue(rows) == pytest.approx(9647.0)\n\n\n"
        "def test_revenue_by_shop(rows):\n"
        "    by_shop = revenue_by_shop(rows)\n"
        '    assert by_shop["Central"] == pytest.approx(5291.0)\n'
        '    assert by_shop["Harbour"] == pytest.approx(4356.0)\n'
        '    assert set(by_shop) == {"Central", "Harbour"}\n\n\n'
        "def test_top_products_best_first(rows):\n"
        '    assert top_products(rows, n=2) == [("Coffee", 120), ("Cinnamon bun", 73)]\n'
        "    assert len(top_products(rows)) == 3\n\n\n"
        "def test_report_lines(rows):\n"
        "    report = format_report(rows)\n"
        '    assert "Total: 9647.00 EUR" in report\n'
        '    assert "Central: 5291.00 EUR" in report\n'
        '    assert "Harbour: 4356.00 EUR" in report\n'
        '    assert "Coffee" in report and "120" in report\n\n\n'
        "def test_main_missing_file_is_polite(capsys):\n"
        '    code = main(["sales_summary", "data/does-not-exist.csv"])\n'
        "    out = capsys.readouterr()\n"
        "    assert code == 1\n"
        '    assert "not found" in (out.out + out.err)\n\n\n'
        "def test_main_prints_report(capsys):\n"
        '    assert main(["sales_summary", str(DATA)]) == 0\n'
        '    assert "Total: 9647.00 EUR" in capsys.readouterr().out\n'
    ),
}


SEEDS: dict[str, dict] = {
    "onboarding": {
        "title": "Onboarding: make the tests pass and hand it in",
        "slug": "onboarding",
        "client": "$company_name (internal)",
        "kind": "code",
        "estimate_hours": 1,
        "due_days": 3,
        "brief": ONBOARDING_BRIEF,
        "acceptance": [
            "`uv sync` has created .venv and `git status` never lists it",
            "`uv run pytest -q` passes both tests",
            "`uv run ruff check .` reports no errors",
            "at least one commit exists after the skeleton commit",
            "a local .env exists and git does not track it",
            "the submit message names one thing that confused you, or quotes the traceback",
        ],
        "learning_goals": [
            "uv venv and sync, and what .venv isolates",
            "reading a pytest failure before touching code",
            "git add, commit, status, and what .gitignore does",
        ],
        "dependencies": [],
        "files": ONBOARDING_FILES,
        "run_command": "uv run pytest -q",
        "boss_notes": "Onboarding. Approve if the tests pass and there is a commit by the learner. "
        "Probe in review: does a gitignored .env exist, and was the traceback read before "
        "the fix?",
        "meeting": None,
    },
    "sales-summary": {
        "title": "Kvernbit daily sales summary",
        "slug": "kvernbit-sales-summary",
        "client": "Kvernbit Bakery",
        "kind": "code",
        "estimate_hours": 2,
        "due_days": 4,
        "brief": SALES_BRIEF,
        "acceptance": [
            "all seven tests in tests/test_sales_summary.py pass",
            "ruff reports no errors",
            'a missing file prints one sentence containing "not found" and exits 1',
            'money is printed with two decimals and the suffix " EUR"',
            "standard library only: no third-party imports",
            "the CSV is read exactly once per run",
        ],
        "learning_goals": [
            "csv.DictReader and converting strings to int and float",
            "loops that accumulate into a dict",
            "sorting a list of tuples by the second element",
            "f-strings with :.2f",
            "a main() that returns an exit code instead of raising",
        ],
        "dependencies": [],
        "files": SALES_FILES,
        "run_command": "uv run pytest -q",
        "boss_notes": "Good solution: load_sales converts types once; revenue_by_shop uses "
        "dict.get or setdefault; top_products sorts by qty descending with sorted(key=...). "
        "Common mistakes: floats summed as strings; sorting ascending; reading the file "
        "twice; catching Exception instead of FileNotFoundError; printing inside helpers. "
        "Probe: ask why the owner-facing text lives in format_report and not in main.",
        "meeting": None,
    },
    "price-labels": {
        "title": "Kvernbit shelf labels",
        "slug": "kvernbit-shelf-labels",
        "client": "Kvernbit Bakery",
        "kind": "code",
        "estimate_hours": 1,
        "due_days": 3,
        "brief": LABELS_BRIEF,
        "acceptance": [
            "all tests in tests/test_labels.py pass",
            "ruff reports no errors",
            "no loops, lists, files, input() or print() in src/labels.py",
            "every function returns its result; none of them prints",
        ],
        "learning_goals": [
            "arithmetic and round()",
            "if / elif / else with boundaries that are easy to get wrong by one",
            "string methods and f-strings with :.2f",
            "the difference between returning and printing",
        ],
        "dependencies": [],
        "files": LABELS_FILES,
        "run_command": "uv run pytest -q",
        "boss_notes": "Good solution: one expression plus round(..., 2); an if / elif / else "
        "with < 3 and < 8; an f-string with .upper() and :.2f. Common mistakes: printing "
        "instead of returning; <= at the band edges; forgetting the two decimals on 3.5. "
        "Probe: what does price_band return for a negative price, and should it?",
        "meeting": None,
    },
}


def _fill(value, names: dict[str, str]):
    if isinstance(value, str):
        return Template(value).safe_substitute(names)
    if isinstance(value, dict):
        return {k: _fill(v, names) for k, v in value.items()}
    if isinstance(value, list):
        return [_fill(v, names) for v in value]
    return value


def seed(cfg: Config, level: Level, ticket_id: str) -> dict | None:
    """The level's named seed with the company, boss and learner filled in. A fresh copy."""
    spec = SEEDS.get(level.seed)
    if spec is None:
        return None
    boss = cfg.section("boss")
    names = {
        "company_name": cfg.company,
        "boss_name": cfg.boss_name,
        "boss_first": cfg.boss_first,
        "boss_title": boss.get("title", "Head of Engineering"),
        "engineer_name": cfg.engineer_name,
        "ticket_id": ticket_id,
    }
    return _fill(copy.deepcopy(spec), names)
