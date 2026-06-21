'''Tests for RelationExtractor.'''

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import pytest

from cdx_brain.retrieval.extractor import RelationExtractor


@dataclass
class FakePolicy:
    id: str
    name: str
    description: str = ''
    trigger_pattern: str = ''


@dataclass
class FakeConcept:
    id: str
    label: str = ''
    description: str = ''


@pytest.fixture
def conn():
    c = sqlite3.connect(':memory:')
    c.row_factory = sqlite3.Row
    yield c
    c.close()


@pytest.fixture
def extractor(conn):
    return RelationExtractor(conn)


class TestTableCreation:

    def test_triples_table_exists(self, conn):
        RelationExtractor(conn)
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='triples'"
        ).fetchone()
        assert row is not None

    def test_triples_columns(self, conn):
        RelationExtractor(conn)
        cols = {
            r['name']: r['type']
            for r in conn.execute("PRAGMA table_info(triples)").fetchall()
        }
        assert cols['id'] == 'TEXT'
        assert cols['subject'] == 'TEXT'
        assert cols['predicate'] == 'TEXT'
        assert cols['object'] == 'TEXT'
        assert cols['confidence'] == 'REAL'
        assert cols['source_type'] == 'TEXT'
        assert cols['metadata'] == 'TEXT'
        assert cols['created_at'] == 'TEXT'
        assert cols['synced'] == 'INTEGER'

    def test_indexes_exist(self, conn):
        RelationExtractor(conn)
        indexes = {
            r['name'] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
        assert 'idx_triples_subject' in indexes
        assert 'idx_triples_predicate' in indexes
        assert 'idx_triples_object' in indexes

    def test_id_is_primary_key(self, conn):
        RelationExtractor(conn)
        pk = conn.execute("PRAGMA table_info(triples)").fetchall()
        pk_cols = [r['name'] for r in pk if r['pk']]
        assert pk_cols == ['id']


class TestFuzzyMatch:

    def test_substring_match(self):
        assert RelationExtractor._fuzzy_match('hello', 'hello world')
        assert RelationExtractor._fuzzy_match('HELLO', 'hello world')
        assert RelationExtractor._fuzzy_match('world', 'hello world')

    def test_token_overlap(self):
        assert RelationExtractor._fuzzy_match(
            'deploy release', 'deploy_fast release_note'
        )
        assert RelationExtractor._fuzzy_match(
            'fix bug crash', 'critical bug fix'
        )

    def test_no_match(self):
        assert not RelationExtractor._fuzzy_match('aaaa', 'bbbb')
        assert not RelationExtractor._fuzzy_match('foo bar', 'baz qux')

    def test_single_token_overlap_not_enough(self):
        assert not RelationExtractor._fuzzy_match('hello foo', 'hello bar')

    def test_empty_strings(self):
        assert not RelationExtractor._fuzzy_match('', 'something')
        assert not RelationExtractor._fuzzy_match('something', '')
        assert not RelationExtractor._fuzzy_match('', '')

    def test_case_insensitive(self):
        assert RelationExtractor._fuzzy_match('DEPLOY', 'Deploy Script')

    def test_underscore_tokens(self):
        assert RelationExtractor._fuzzy_match(
            'fast_deploy', 'deploy_script fast_rollback'
        )


class TestExtractTriggers:

    def test_basic_trigger(self, extractor):
        policies = [
            FakePolicy(id='p1', name='p1_name', trigger_pattern='deploy', description=''),
            FakePolicy(id='p2', name='deploy_tool', trigger_pattern='', description=''),
        ]
        count = extractor.extract(policies, [])
        assert count >= 1

    def test_no_trigger_no_edge(self, extractor):
        policies = [
            FakePolicy(id='p1', name='alpha', trigger_pattern='xxx', description=''),
            FakePolicy(id='p2', name='beta', trigger_pattern='yyy', description=''),
        ]
        count = extractor.extract(policies, [])
        assert count == 0

    def test_self_loop_skipped(self, extractor):
        policies = [
            FakePolicy(id='p1', name='deploy', trigger_pattern='deploy', description=''),
        ]
        count = extractor.extract(policies, [])
        assert count == 0

    def test_policy_a_triggers_b(self, extractor):
        policies = [
            FakePolicy(id='p1', name='x', trigger_pattern='target_func', description=''),
            FakePolicy(id='p2', name='target_func', trigger_pattern='', description=''),
        ]
        count = extractor.extract(policies, [])
        assert count == 1

    def test_deduplication(self, extractor):
        policies = [
            FakePolicy(id='p1', name='deploy_script', trigger_pattern='', description=''),
            FakePolicy(id='p2', name='fast_release', trigger_pattern='deploy release', description=''),
        ]
        extractor.extract(policies, [])
        count2 = extractor.extract(policies, [])
        assert count2 == 0


class TestExtractRelatesTo:

    def test_similar_descriptions(self, extractor):
        items = [
            FakePolicy(id='p1', name='svc1', description='This is a user authentication service'),
            FakeConcept(id='c1', label='auth', description='user authentication module and login'),
        ]
        count = extractor.extract(items[:1], items[1:])
        assert count == 1

    def test_dissimilar_descriptions(self, extractor):
        items = [
            FakePolicy(id='p1', name='svc1', description='aaa bbb ccc ddd'),
            FakeConcept(id='c1', label='auth', description='xxx yyy zzz'),
        ]
        count = extractor.extract(items[:1], items[1:])
        assert count == 0

    def test_undirected_single_edge(self, extractor):
        items = [
            FakePolicy(id='p1', name='a', description='common description here'),
            FakePolicy(id='p2', name='b', description='common description there'),
        ]
        count = extractor.extract(items, [])
        assert count == 1

    def test_deduplication_relates_to(self, extractor):
        items = [
            FakePolicy(id='p1', name='a', description='common description here'),
            FakePolicy(id='p2', name='b', description='common description there'),
        ]
        extractor.extract(items, [])
        count2 = extractor.extract(items, [])
        assert count2 == 0

    def test_empty_descriptions_skipped(self, extractor):
        items = [
            FakePolicy(id='p1', name='a', description=''),
            FakePolicy(id='p2', name='b', description='some text here'),
        ]
        count = extractor.extract(items, [])
        assert count == 0


class TestGetStats:

    def test_empty(self, extractor):
        stats = extractor.get_stats()
        assert stats['total_edges'] == 0
        assert stats['by_predicate'] == {}
        assert stats['orphan_subjects'] == []

    def test_total_and_by_predicate(self, extractor):
        policies = [
            FakePolicy(id='p1', name='build_deploy', trigger_pattern='build', description=''),
            FakePolicy(id='p2', name='build_tool', trigger_pattern='', description=''),
            FakePolicy(id='p3', name='test_runner', trigger_pattern='test', description=''),
            FakePolicy(id='p4', name='test_suite', trigger_pattern='', description=''),
        ]
        extractor.extract(policies, [])
        stats = extractor.get_stats()
        assert stats['total_edges'] == 2
        assert stats['by_predicate'] == {'triggers': 2}
        assert sorted(stats['orphan_subjects']) == ['p1', 'p3']

    def test_mixed_relates_to_and_triggers(self, extractor):
        policies = [
            FakePolicy(id='p1', name='a', trigger_pattern='target_b', description='common description here'),
            FakePolicy(id='p2', name='target_b', trigger_pattern='', description='common description there'),
        ]
        extractor.extract(policies, [])
        stats = extractor.get_stats()
        assert stats['total_edges'] >= 2
        assert 'triggers' in stats['by_predicate']
        assert 'relates_to' in stats['by_predicate']

    def test_no_orphans_when_relates_to_exists(self, extractor):
        policies = [
            FakePolicy(id='p_a', name='alpha', trigger_pattern='alpha', description='same description block'),
            FakePolicy(id='p_b', name='beta', trigger_pattern='', description='same description block'),
        ]
        extractor.extract(policies, [])
        stats = extractor.get_stats()
        assert stats['total_edges'] == 1
        assert stats['by_predicate'] == {'relates_to': 1}
        assert stats['orphan_subjects'] == []


