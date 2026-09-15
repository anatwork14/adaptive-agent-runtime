"""Unit tests for indexes (Lexical FTS5, Vector, Symbol)."""

import sqlite3

from indexes.lexical import LexicalIndex
from indexes.symbols import SymbolIndex
from indexes.vector import VectorIndex


def test_lexical_fts5_index():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    idx = LexicalIndex(conn)

    idx.index_document("M1", "Login API", "AuthClient returns AuthResult with security tokens", "auth login")
    idx.index_document("M2", "Database Setup", "PostgreSQL service runs on port 5432", "db postgres")

    hits = idx.search("AuthResult")
    assert len(hits) == 1
    assert hits[0][0] == "M1"

    hits_db = idx.search("postgres")
    assert len(hits_db) == 1
    assert hits_db[0][0] == "M2"

    conn.close()


def test_vector_index_cosine_similarity():
    idx = VectorIndex(dimension=4)
    idx.add_vector("doc1", [1.0, 0.0, 0.0, 0.0])
    idx.add_vector("doc2", [0.0, 1.0, 0.0, 0.0])
    idx.add_vector("doc3", [0.9, 0.1, 0.0, 0.0])

    res = idx.search([1.0, 0.0, 0.0, 0.0], top_k=2)
    assert len(res) == 2
    assert res[0][0] == "doc1"
    assert res[1][0] == "doc3"


def test_symbol_extraction():
    idx = SymbolIndex()
    code = """
class AuthClient:
    def login(self, username: str):
        return True

def standalone_helper():
    pass
"""
    idx.index_python_file("src/auth.py", code)

    auth_syms = idx.lookup_symbol("AuthClient")
    assert len(auth_syms) == 1
    assert auth_syms[0].kind == "class"

    login_syms = idx.lookup_symbol("login")
    assert len(login_syms) == 1
    assert login_syms[0].kind == "function"

    helper_syms = idx.lookup_symbol("standalone_helper")
    assert len(helper_syms) == 1
