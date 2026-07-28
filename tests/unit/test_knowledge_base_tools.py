"""Tests for knowledge base tools."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.message.components import File, Reply
from astrbot.core.tools.knowledge_base_tools import (
    KnowledgeBaseImportAttachmentTool,
)


def _make_kb_helper(kb_id: str, kb_name: str):
    """Create a mock knowledge base helper."""
    return SimpleNamespace(
        kb=SimpleNamespace(kb_id=kb_id, kb_name=kb_name),
        import_wiki_sources=AsyncMock(
            return_value={"imported": [{"path": "category/page.md"}], "skipped": []}
        ),
    )


def _make_kb_manager(*helpers):
    """Create a mock knowledge base manager for the supplied helpers."""
    helpers_by_id = {helper.kb.kb_id: helper for helper in helpers}
    helpers_by_name = {helper.kb.kb_name: helper for helper in helpers}
    return SimpleNamespace(
        get_kb=AsyncMock(side_effect=helpers_by_id.get),
        get_kb_by_name=AsyncMock(side_effect=helpers_by_name.get),
        list_kbs=AsyncMock(return_value=[helper.kb for helper in helpers]),
    )


def _make_context(components, kb_manager, *, role: str = "admin", config=None):
    """Create a tool execution context with the given message components."""
    event = SimpleNamespace(
        role=role,
        unified_msg_origin="feishu:private:test-user",
        message_obj=SimpleNamespace(message=components),
    )
    plugin_context = SimpleNamespace(
        kb_manager=kb_manager,
        get_config=lambda **_kwargs: config or {},
    )
    return ContextWrapper(context=SimpleNamespace(event=event, context=plugin_context))


@pytest.mark.asyncio
async def test_import_attachment_requires_administrator(tmp_path):
    """Reject knowledge imports from non-administrator users."""
    source = tmp_path / "guide.md"
    source.write_text("# Guide", encoding="utf-8")
    helper = _make_kb_helper("kb-1", "Docs")
    manager = _make_kb_manager(helper)
    context = _make_context(
        [File(name=source.name, file=str(source))],
        manager,
        role="member",
    )

    result = await KnowledgeBaseImportAttachmentTool().call(
        context,
        knowledge_base="kb-1",
    )

    assert result == "error: Only administrators can import knowledge base attachments."
    manager.get_kb.assert_not_awaited()
    helper.import_wiki_sources.assert_not_awaited()


@pytest.mark.asyncio
async def test_import_attachment_uses_single_current_file_by_default(tmp_path):
    """Use the only current-message attachment when no name is supplied."""
    source = tmp_path / "guide.md"
    source.write_text("# Guide", encoding="utf-8")
    helper = _make_kb_helper("kb-1", "Docs")
    manager = _make_kb_manager(helper)
    context = _make_context([File(name=source.name, file=str(source))], manager)

    result = await KnowledgeBaseImportAttachmentTool().call(
        context,
        knowledge_base="kb-1",
        overwrite=True,
    )

    assert result.startswith("Imported 1 Wiki pages into Docs (kb-1).")
    manager.get_kb.assert_awaited_once_with("kb-1")
    helper.import_wiki_sources.assert_awaited_once_with(
        [(Path(source), "guide.md")],
        overwrite=True,
    )


@pytest.mark.asyncio
async def test_import_attachment_finds_file_in_quoted_message(tmp_path):
    """Find a file attachment embedded in a quoted message chain."""
    source = tmp_path / "quoted.zip"
    source.write_bytes(b"zip fixture")
    helper = _make_kb_helper("kb-1", "Docs")
    manager = _make_kb_manager(helper)
    reply = Reply(
        id="message-id",
        chain=[File(name=source.name, file=str(source))],
    )
    context = _make_context([reply], manager)

    await KnowledgeBaseImportAttachmentTool().call(
        context,
        knowledge_base="kb-1",
    )

    helper.import_wiki_sources.assert_awaited_once_with(
        [(Path(source), None)],
        overwrite=False,
    )


@pytest.mark.asyncio
async def test_import_attachment_selects_named_file_case_insensitively(tmp_path):
    """Select an exact attachment name when multiple files are present."""
    first = tmp_path / "first.md"
    second = tmp_path / "second.zip"
    first.write_text("# First", encoding="utf-8")
    second.write_bytes(b"zip fixture")
    helper = _make_kb_helper("kb-1", "Docs")
    manager = _make_kb_manager(helper)
    context = _make_context(
        [
            File(name=first.name, file=str(first)),
            File(name=second.name, file=str(second)),
        ],
        manager,
    )

    await KnowledgeBaseImportAttachmentTool().call(
        context,
        attachment_name="SECOND.ZIP",
        knowledge_base="kb-1",
    )

    helper.import_wiki_sources.assert_awaited_once_with(
        [(Path(second), None)],
        overwrite=False,
    )


@pytest.mark.asyncio
async def test_import_attachment_requires_name_for_multiple_files(tmp_path):
    """Reject an ambiguous request containing multiple attachments."""
    helper = _make_kb_helper("kb-1", "Docs")
    manager = _make_kb_manager(helper)
    context = _make_context(
        [
            File(name="first.md", file=str(tmp_path / "first.md")),
            File(name="second.zip", file=str(tmp_path / "second.zip")),
        ],
        manager,
    )

    result = await KnowledgeBaseImportAttachmentTool().call(context)

    assert result == (
        "error: Multiple attachments found; specify one of: first.md, second.zip"
    )
    manager.get_kb.assert_not_awaited()
    helper.import_wiki_sources.assert_not_awaited()


@pytest.mark.asyncio
async def test_import_attachment_rejects_unsupported_file_type(tmp_path):
    """Reject attachments that are neither Markdown nor ZIP files."""
    helper = _make_kb_helper("kb-1", "Docs")
    manager = _make_kb_manager(helper)
    context = _make_context(
        [File(name="notes.txt", file=str(tmp_path / "notes.txt"))],
        manager,
    )

    result = await KnowledgeBaseImportAttachmentTool().call(
        context,
        knowledge_base="kb-1",
    )

    assert result == "error: Only Markdown files and ZIP archives are supported."
    manager.get_kb.assert_not_awaited()
    helper.import_wiki_sources.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("selector", "expected_id_calls", "expected_name_calls"),
    [
        ("kb-1", ["kb-1"], []),
        ("Docs", ["Docs"], ["Docs"]),
    ],
)
async def test_import_attachment_resolves_explicit_kb_id_or_name(
    tmp_path,
    selector,
    expected_id_calls,
    expected_name_calls,
):
    """Resolve an explicitly supplied knowledge base ID or name."""
    source = tmp_path / "guide.md"
    source.write_text("# Guide", encoding="utf-8")
    helper = _make_kb_helper("kb-1", "Docs")
    manager = _make_kb_manager(helper)
    context = _make_context([File(name=source.name, file=str(source))], manager)

    await KnowledgeBaseImportAttachmentTool().call(
        context,
        knowledge_base=selector,
    )

    assert [
        call.args[0] for call in manager.get_kb.await_args_list
    ] == expected_id_calls
    assert [
        call.args[0] for call in manager.get_kb_by_name.await_args_list
    ] == expected_name_calls
    helper.import_wiki_sources.assert_awaited_once()


@pytest.mark.asyncio
async def test_import_attachment_uses_single_session_kb(tmp_path, monkeypatch):
    """Automatically select the only knowledge base configured for the session."""
    source = tmp_path / "guide.md"
    source.write_text("# Guide", encoding="utf-8")
    helper = _make_kb_helper("kb-1", "Docs")
    manager = _make_kb_manager(helper)
    context = _make_context([File(name=source.name, file=str(source))], manager)
    session_get = AsyncMock(return_value={"kb_ids": ["kb-1"]})
    monkeypatch.setattr(
        "astrbot.core.tools.knowledge_base_tools.sp.session_get",
        session_get,
    )

    result = await KnowledgeBaseImportAttachmentTool().call(context)

    assert result.startswith("Imported 1 Wiki pages into Docs (kb-1).")
    session_get.assert_awaited_once_with(
        "feishu:private:test-user",
        "kb_config",
        default={},
    )
    manager.get_kb.assert_awaited_once_with("kb-1")
    helper.import_wiki_sources.assert_awaited_once()


@pytest.mark.asyncio
async def test_import_attachment_does_not_fallback_when_session_disables_kbs(
    tmp_path,
    monkeypatch,
):
    """Respect an explicit empty session knowledge base selection."""
    source = tmp_path / "guide.md"
    source.write_text("# Guide", encoding="utf-8")
    helper = _make_kb_helper("kb-1", "Docs")
    manager = _make_kb_manager(helper)
    context = _make_context([File(name=source.name, file=str(source))], manager)
    monkeypatch.setattr(
        "astrbot.core.tools.knowledge_base_tools.sp.session_get",
        AsyncMock(return_value={"kb_ids": []}),
    )

    result = await KnowledgeBaseImportAttachmentTool().call(context)

    assert result == (
        "error: Specify the target knowledge base because the current session "
        "does not resolve to exactly one."
    )
    manager.list_kbs.assert_not_awaited()
    manager.get_kb.assert_not_awaited()
    helper.import_wiki_sources.assert_not_awaited()


@pytest.mark.asyncio
async def test_import_attachment_requires_target_for_multiple_session_kbs(
    tmp_path,
    monkeypatch,
):
    """Require an explicit target when the session has multiple knowledge bases."""
    source = tmp_path / "guide.md"
    source.write_text("# Guide", encoding="utf-8")
    docs = _make_kb_helper("kb-1", "Docs")
    handbook = _make_kb_helper("kb-2", "Handbook")
    manager = _make_kb_manager(docs, handbook)
    context = _make_context([File(name=source.name, file=str(source))], manager)
    monkeypatch.setattr(
        "astrbot.core.tools.knowledge_base_tools.sp.session_get",
        AsyncMock(return_value={"kb_ids": ["kb-1", "kb-2"]}),
    )

    result = await KnowledgeBaseImportAttachmentTool().call(context)

    assert result == (
        "error: Specify the target knowledge base because the current session "
        "does not resolve to exactly one. Current candidates: Docs, Handbook."
    )
    docs.import_wiki_sources.assert_not_awaited()
    handbook.import_wiki_sources.assert_not_awaited()


@pytest.mark.asyncio
async def test_import_attachment_sanitizes_local_paths_in_errors(tmp_path):
    """Do not expose the downloaded attachment path in tool errors."""
    source = tmp_path / "guide.md"
    source.write_text("# Guide", encoding="utf-8")
    helper = _make_kb_helper("kb-1", "Docs")
    helper.import_wiki_sources.side_effect = ValueError(
        f"Markdown file is not valid UTF-8: {source}"
    )
    manager = _make_kb_manager(helper)
    context = _make_context([File(name=source.name, file=str(source))], manager)

    result = await KnowledgeBaseImportAttachmentTool().call(
        context,
        knowledge_base="kb-1",
    )

    assert result == (
        "error: Knowledge import failed: Markdown file is not valid UTF-8: guide.md"
    )
    assert str(source) not in result
