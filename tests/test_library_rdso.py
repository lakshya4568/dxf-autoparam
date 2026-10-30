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


def test_the_manifest_the_builder_reads_names_every_standard_the_sheet_holds():
    """Adding a set of standard drawings is a row of rdso/standards.json and a run of the builder: the sets the sheet holds are those rows."""
    import importlib.util
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("build_rdso_sheet", root / "tools" / "build_rdso_sheet.py")
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    rows = builder.load_standards()
    assert [r["id"] for r in rows] == [s["id"] for s in L.open_domain("bridge").rdso_sheet["standards"]]
    assert all(isinstance(p, int) for r in rows for part in r["parts"] for p in part["spot_checked"]), "a page is a number"
    raw = json.loads((root / "src/dxf_autoparam/knowledge/library/bridge/rdso/standards.json").read_text())
    assert not any(k in json.dumps(raw["standards"]) for k in ("thickness", "_mm\"")), "the manifest holds where values are read, never a value"


def test_a_second_family_s_sheet_plugs_in_and_a_sheet_not_extracted_yet_is_nothing(tmp_path):
    """The integration point for standards still to be extracted: a domain lists its sheets; a sheet of another family is read record by record;
    a sheet named but not on disk gives nothing (no standard is made up for it)."""
    import json
    import shutil

    src = L.open_domain("bridge").dir
    d = tmp_path / "bridge"
    shutil.copytree(src, d)
    meta = json.loads((d / "domain.json").read_text())
    meta.pop("rdso_sheet", None)
    meta["rdso_sheets"] = ["rdso/rdso_rcc_box_index.json", "rdso/slab_sheet.json", "rdso/not_extracted_yet.json"]
    (d / "domain.json").write_text(json.dumps(meta))
    (d / "rdso" / "slab_sheet.json").write_text(json.dumps({
        "kinds": {"explicit": "printed"}, "rules_of_use": ["context only"],
        "standards": [{"id": "RDSO-SLAB-TEST", "series": "TEST/SLAB", "title": "a test sheet", "structure": "slab", "track": "single line", "loading": "test",
                       "extraction_status": "test"}],
        "tables": [{"standard": "RDSO-SLAB-TEST", "table": "T1", "rows": [["span", "depth"]], "sheet": 1, "page": 1, "kind": "explicit"},
                   {"standard": "OTHER", "table": "T9"}]}))
    lib = L.Library(d)
    assert len(lib.rdso_sheets) == 2, "the one not extracted yet is no sheet"
    listed = {s["id"] for s in lib.reference("rdso-sheet:")["standards"]}
    assert "RDSO-SLAB-TEST" in listed and len(listed) == 6
    r = lib.reference("rdso-sheet:RDSO-SLAB-TEST")
    assert r["found"] and r["standard"]["structure"] == "slab" and [t["table"] for t in r["tables"]] == ["T1"], "only its own records"
    box = lib.reference("rdso-sheet:")["standards"][0]["id"]
    assert lib.reference(f"rdso-sheet:{box}")["schedule_rows"] > 0, "the box sheet reads as before"
