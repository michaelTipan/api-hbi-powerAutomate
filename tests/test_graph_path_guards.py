"""Guards de rutas Graph documentales."""

from app.application.services.graph_path_guards import is_drive_document_path


def test_is_drive_document_path_drive_item() -> None:
    assert is_drive_document_path("/sites/x/drives/d1/root:/folder/file.pdf:")
    assert is_drive_document_path("drives/abc/items/item123/content")


def test_is_drive_document_path_excludes_lists() -> None:
    assert not is_drive_document_path("/sites/x/lists/list1/items")
    assert not is_drive_document_path("/sites/x/lists/list1/items/1")


def test_is_drive_document_path_ignores_query() -> None:
    assert is_drive_document_path("/drives/d1/items/i1?$select=id,name")
