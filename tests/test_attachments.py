import pytest

from attachments import (
    AttachmentError,
    complete_path_reference,
    find_inline_attachments,
    format_attachment_preview,
    resolve_attachment,
)


def test_resolve_attachment_records_metadata(tmp_path):
    image = tmp_path / "photo.png"
    image.write_bytes(b"png bytes")

    attachment = resolve_attachment("photo.png", cwd=tmp_path)

    assert attachment.path == image.resolve()
    assert attachment.filename == "photo.png"
    assert attachment.mime_type == "image/png"
    assert attachment.size_bytes == 9


def test_find_inline_attachments_ignores_ordinary_mentions(tmp_path):
    target = tmp_path / "notes.txt"
    target.write_text("hello")

    found = find_inline_attachments("email @Amanda @notes.txt", cwd=tmp_path)

    assert [item.filename for item in found] == ["notes.txt"]


def test_complete_path_reference_replaces_only_final_token(tmp_path):
    (tmp_path / "photo.png").write_bytes(b"x")

    assert complete_path_reference("look at @pho", cwd=tmp_path) == [
        "look at @photo.png"
    ]


def test_image_attachment_rejects_non_image(tmp_path):
    document = tmp_path / "notes.txt"
    document.write_text("hello")

    with pytest.raises(AttachmentError, match="image"):
        resolve_attachment("notes.txt", cwd=tmp_path, image_only=True)


def test_format_attachment_preview_contains_safe_metadata(tmp_path):
    document = tmp_path / "notes.txt"
    document.write_text("hello")

    preview = format_attachment_preview(resolve_attachment("notes.txt", cwd=tmp_path))

    assert "notes.txt" in preview
    assert "text/plain" in preview
    assert "5 bytes" in preview
    assert "hello" not in preview
