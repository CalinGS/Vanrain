import dataclasses

import pytest

from vanrain.model import (
    Detail,
    Edge,
    EdgeKind,
    NodeKind,
    ParseResult,
    Reference,
    Selection,
    SelectionItem,
    Symbol,
)


def make_symbol(**overrides):
    fields = dict(
        id="pkg.mod.Class.method",
        kind=NodeKind.METHOD,
        file="pkg/mod.py",
        span=(10, 20),
        signature="def method(self) -> None:",
        tokens_full=120,
        tokens_sig=12,
    )
    fields.update(overrides)
    return Symbol(**fields)


def test_enum_members():
    assert [k.name for k in NodeKind] == ["MODULE", "CLASS", "FUNCTION", "METHOD"]
    assert [k.name for k in EdgeKind] == [
        "CALLS", "IMPORTS", "INHERITS", "REFERENCES", "CONTAINS",
    ]
    assert [d.name for d in Detail] == ["FULL", "SIGNATURE"]


def test_enums_round_trip_through_strings():
    for enum in (NodeKind, EdgeKind, Detail):
        for member in enum:
            assert enum(member.value) is member
            assert member == member.value  # str enum: serialises as plain text


def test_symbol_is_frozen_and_hashable():
    sym = make_symbol()
    with pytest.raises(dataclasses.FrozenInstanceError):
        sym.id = "other"
    assert {sym, make_symbol()} == {sym}


def test_edge_defaults_and_identity():
    e = Edge("a.f", "a.g", EdgeKind.CALLS)
    assert e.confidence == 1.0
    assert e == Edge("a.f", "a.g", EdgeKind.CALLS, 1.0)
    assert e != Edge("a.f", "a.g", EdgeKind.REFERENCES)
    assert len({e, Edge("a.f", "a.g", EdgeKind.CALLS)}) == 1
    with pytest.raises(dataclasses.FrozenInstanceError):
        e.confidence = 0.5


def test_parse_result_defaults_are_empty_tuples():
    pr = ParseResult(file="pkg/mod.py", module="pkg.mod")
    assert pr.symbols == () and pr.references == () and pr.edges == ()
    ref = Reference("pkg.mod.f", "util.helper", EdgeKind.CALLS, 3)
    pr2 = ParseResult("pkg/mod.py", "pkg.mod", (make_symbol(),), (ref,))
    assert hash(pr2)  # all-tuple fields keep it hashable


def test_selection_is_mutable_with_independent_defaults():
    a = Selection(seeds=("pkg.mod.f",), budget=2000)
    b = Selection(seeds=("pkg.mod.g",), budget=2000)
    a.items.append(SelectionItem("pkg.mod.f", Detail.FULL, 0))
    a.tokens_used += 150
    assert b.items == [] and b.tokens_used == 0
    assert a.items[0].detail is Detail.FULL
