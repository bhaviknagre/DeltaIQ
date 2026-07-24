from src.canonical.model import ElementType
from src.delta.criticality import Criticality, classify_criticality
from src.delta.engine import ChangeKind


def test_dimension_modified_is_red():
    assert classify_criticality(ChangeKind.MODIFIED, ElementType.DIMENSION) == Criticality.RED


def test_dimension_removed_is_red():
    assert classify_criticality(ChangeKind.REMOVED, ElementType.DIMENSION) == Criticality.RED


def test_tag_removed_is_red():
    assert classify_criticality(ChangeKind.REMOVED, ElementType.TAG) == Criticality.RED


def test_tag_modified_is_yellow():
    assert classify_criticality(ChangeKind.MODIFIED, ElementType.TAG) == Criticality.YELLOW


def test_dimension_added_is_yellow():
    assert classify_criticality(ChangeKind.ADDED, ElementType.DIMENSION) == Criticality.YELLOW


def test_note_removed_is_yellow():
    assert classify_criticality(ChangeKind.REMOVED, ElementType.NOTE) == Criticality.YELLOW


def test_note_added_is_green():
    assert classify_criticality(ChangeKind.ADDED, ElementType.NOTE) == Criticality.GREEN


def test_text_modified_is_green():
    assert classify_criticality(ChangeKind.MODIFIED, ElementType.TEXT) == Criticality.GREEN
