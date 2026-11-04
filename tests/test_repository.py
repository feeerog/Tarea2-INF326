from concurrent.futures import ThreadPoolExecutor

import pytest

from shortener.common.base62 import ALPHABET, INITIAL_ID, encode
from shortener.common.database import UrlRepository, connection


@pytest.mark.parametrize(
    "number,expected", [(0, "0"), (61, "z"), (62, "10"), (INITIAL_ID, "eRgfR")]
)
def test_base62_known_values(number, expected):
    assert encode(number) == expected


def test_base62_large_range_is_injective_and_roundtrips():
    numbers = [*range(INITIAL_ID, INITIAL_ID + 5000), 2**63 - 1]
    codes = [encode(number) for number in numbers]
    assert len(codes) == len(set(codes))
    for number, code in zip(numbers, codes, strict=True):
        decoded = 0
        for character in code:
            decoded = decoded * 62 + ALPHABET.index(character)
        assert decoded == number


def test_first_id_restart_and_no_reuse_after_delete(tmp_path):
    path = tmp_path / "urls.db"
    repository = UrlRepository(path)
    repository.initialize()
    first = repository.create("https://usm.cl/uno")
    second = repository.create("https://usm.cl/dos")
    assert first.id == INITIAL_ID
    assert second.id == INITIAL_ID + 1
    with connection(path) as conn:
        conn.execute("DELETE FROM urls WHERE id=?", (second.id,))
    restarted = UrlRepository(path)
    restarted.initialize()
    assert restarted.get(first.hash) == first
    assert restarted.create("https://usm.cl/tres").id == INITIAL_ID + 2


def test_concurrent_independent_connections_allocate_unique_ids(tmp_path):
    path = tmp_path / "urls.db"
    UrlRepository(path).initialize()

    def create(index):
        return UrlRepository(path).create(f"https://usm.cl/{index}")

    with ThreadPoolExecutor(max_workers=12) as pool:
        records = list(pool.map(create, range(60)))
    assert sorted(record.id for record in records) == list(range(INITIAL_ID, INITIAL_ID + 60))
    assert len({record.hash for record in records}) == 60
    for record in records:
        assert UrlRepository(path).get(record.hash) == record


def test_duplicate_url_gets_new_id_and_sql_text_stays_data(tmp_path):
    repository = UrlRepository(tmp_path / "urls.db")
    repository.initialize()
    value = "https://usm.cl/?q=';DROP_TABLE_urls;--"
    first, second = repository.create(value), repository.create(value)
    assert second.id == first.id + 1
    assert repository.get(first.hash).long_url == value
    assert repository.get("' OR 1=1 --") is None
