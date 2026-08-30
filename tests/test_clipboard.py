import pytest

import clipboard


@pytest.mark.asyncio
async def test_copy_text_reports_when_no_native_clipboard_is_available(monkeypatch):
    monkeypatch.setattr(clipboard, "find_clipboard_command", lambda: None)

    with pytest.raises(clipboard.ClipboardError, match="no supported clipboard command"):
        await clipboard.copy_text("visible transcript")
