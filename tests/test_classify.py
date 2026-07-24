from src.canonical.model import ElementType
from src.ingest.classify import classify_text


def test_classifies_equipment_tag():
    assert classify_text("26-KA-902") == ElementType.TAG


def test_classifies_dimension_with_fraction_inch():
    assert classify_text('3/4"-DC-26-9026-FC11S-00') == ElementType.DIMENSION


def test_classifies_numbered_note():
    assert classify_text("1. FIRST NOTE") == ElementType.NOTE
    assert classify_text("NOTE 26") == ElementType.NOTE


def test_classifies_generic_text():
    assert classify_text("COMP. CASING DRAIN") == ElementType.TEXT


def test_classifies_empty_string_as_text():
    assert classify_text("") == ElementType.TEXT
    assert classify_text("   ") == ElementType.TEXT
