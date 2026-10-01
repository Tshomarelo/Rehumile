"""Production tables are utf8mb3 (3 bytes per character): anything stored in the database must stay in the Basic Multilingual Plane."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
FOUR_BYTE = re.compile('[\U00010000-\U0010FFFF]')


def test_seed_and_migration_data_has_no_emoji():
    files = [ROOT / 'ims' / 'website_defaults.py', ROOT / 'ims' / 'ledger.py', ROOT / 'ims' / 'billing.py', ROOT / 'ims' / 'recurring.py']
    files += list((ROOT / 'ims' / 'migrations').glob('*.py')) + list((ROOT / 'HR' / 'migrations').glob('*.py'))
    files += list((ROOT / 'HR').rglob('seed*.py')) + list((ROOT / 'HR' / 'management').rglob('*.py'))
    bad = [f"{f.relative_to(ROOT)}:{i}" for f in files if f.exists() for i, line in enumerate(f.read_text(encoding='utf8').splitlines(), 1) if FOUR_BYTE.search(line)]
    assert not bad, bad


def test_default_website_content_is_mysql_safe():
    from ims import website_defaults as w
    text = ' '.join(str(x) for row in list(w.CONTENT_DEFAULTS) + list(w.PRICE_DEFAULTS) for x in row)
    assert not FOUR_BYTE.search(text)
