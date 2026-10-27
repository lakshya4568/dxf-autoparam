"""The standard-drawing sheet in the bridge library: listed, read per standard and per schedule row, each value with its sheet and kind."""

from __future__ import annotations

from dxf_autoparam.ai import library as L


def test_the_sheet_lists_its_standards_and_what_each_applies_to():
    lib = L.open_domain("bridge")
    r = lib.reference("rdso-sheet:")
    assert r["found"] and len(r["standards"]) == 5
    assert all(s["structure"] and s["loading"] and s["extraction_status"] for s in r["standards"])
    assert "never" in r["context_only"]


def test_a_standard_reads_with_its_tables_and_a_row_with_its_sheet():
    lib = L.open_domain("bridge")
    sid = lib.reference("rdso-sheet:")["standards"][0]["id"]
    r = lib.reference(f"rdso-sheet:{sid}")
    assert r["found"] and r["haunch"] and r["schedule_rows"] > 0 and "schedule" not in r
    assert "schedule" in lib.reference(f"rdso-sheet:{sid}", full=True)
    row = lib.reference(f"rdso-sheet:{sid}", full=True)["schedule"][0]
    one = lib.reference(f"rdso-sheet:{sid}:{row['fill_m']:g}:{row['config']}")
    assert one["found"] and one["row"]["drawing"] and one["row"]["kind"] in ("explicit", "unverified")


def test_ids_resolve_only_when_they_name_something():
    lib = L.open_domain("bridge")
    sid = lib.reference("rdso-sheet:")["standards"][0]["id"]
    assert lib.resolves(f"rdso-sheet:{sid}") and not lib.resolves("rdso-sheet:NO-SUCH") and lib.is_library_id("rdso-sheet:x")
