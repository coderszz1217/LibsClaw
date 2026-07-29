import asyncio
import re
from pathlib import Path

from pydantic import Field
from pydantic.dataclasses import dataclass

from astrbot.api import logger, sp
from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import FunctionTool, ToolExecResult
from astrbot.core.astr_agent_context import AstrAgentContext
from astrbot.core.knowledge_base.kb_helper import KBHelper
from astrbot.core.knowledge_base.models import (
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_SIZE,
    KBDocument,
)
from astrbot.core.message.components import File, Reply
from astrbot.core.message.message_event_result import MessageEventResult
from astrbot.core.platform.astr_message_event import AstrMessageEvent
from astrbot.core.star.context import Context
from astrbot.core.tools.registry import builtin_tool

_KNOWLEDGE_BASE_TOOL_CONFIG = {
    "kb_agentic_mode": True,
}


async def _resolve_target_knowledge_base(
    event: AstrMessageEvent,
    plugin_context: Context,
    selector: str,
) -> tuple[KBHelper | None, str | None]:
    """Resolve one writable knowledge base for an agent tool call.

    Args:
        event: Current platform message event.
        plugin_context: Runtime context containing the knowledge base manager.
        selector: Optional knowledge base name or stable identifier.

    Returns:
        A tuple containing the resolved helper and an optional user-facing error.
    """
    kb_manager = plugin_context.kb_manager
    if selector:
        kb_helper = await kb_manager.get_kb(selector)
        if kb_helper is None:
            kb_helper = await kb_manager.get_kb_by_name(selector)
        if kb_helper is None:
            return None, f"error: Knowledge base {selector!r} does not exist."
        return kb_helper, None

    configured_helpers = []
    session_config = await sp.session_get(
        event.unified_msg_origin,
        "kb_config",
        default={},
    )
    has_explicit_session_selection = bool(session_config and "kb_ids" in session_config)
    if has_explicit_session_selection:
        for kb_id in session_config.get("kb_ids", []):
            helper = await kb_manager.get_kb(kb_id)
            if helper is not None:
                configured_helpers.append(helper)
    else:
        config = plugin_context.get_config(umo=event.unified_msg_origin)
        for kb_name in config.get("kb_names", []):
            helper = await kb_manager.get_kb_by_name(kb_name)
            if helper is not None:
                configured_helpers.append(helper)

    unique_helpers = {helper.kb.kb_id: helper for helper in configured_helpers}
    if not unique_helpers and not has_explicit_session_selection:
        all_kbs = await kb_manager.list_kbs()
        if len(all_kbs) == 1:
            only_kb = all_kbs[0]
            helper = await kb_manager.get_kb(only_kb.kb_id)
            if helper is not None:
                unique_helpers[only_kb.kb_id] = helper
    if len(unique_helpers) != 1:
        names = ", ".join(helper.kb.kb_name for helper in unique_helpers.values())
        suffix = f" Current candidates: {names}." if names else ""
        return None, (
            "error: Specify the target knowledge base because the current "
            f"session does not resolve to exactly one.{suffix}"
        )
    return next(iter(unique_helpers.values())), None


async def retrieve_knowledge_base(
    query: str,
    umo: str,
    context: Context,
) -> str | None:
    """Retrieve knowledge base context for the given query."""
    kb_mgr = context.kb_manager
    config = context.get_config(umo=umo)

    session_config = await sp.session_get(umo, "kb_config", default={})
    kb_ids: list[str] = []
    kb_names: list[str] = []
    if session_config and "kb_ids" in session_config:
        kb_ids = session_config.get("kb_ids", [])
        if not kb_ids:
            logger.info(f"[知识库] 会话 {umo} 已被配置为不使用知识库")
            return None

        top_k = session_config.get("top_k", 5)
        invalid_kb_ids = []
        for kb_id in kb_ids:
            kb_helper = await kb_mgr.get_kb(kb_id)
            if kb_helper:
                kb_names.append(kb_helper.kb.kb_name)
            else:
                logger.warning(f"[知识库] 知识库不存在或未加载: {kb_id}")
                invalid_kb_ids.append(kb_id)

        if invalid_kb_ids:
            logger.warning(
                f"[知识库] 会话 {umo} 配置的以下知识库无效: {invalid_kb_ids}",
            )
        if not kb_names:
            return None
        logger.debug(f"[知识库] 使用会话级配置，知识库数量: {len(kb_names)}")
    else:
        kb_names = config.get("kb_names", [])
        top_k = config.get("kb_final_top_k", 5)
        logger.debug(f"[知识库] 使用全局配置，知识库数量: {len(kb_names)}")

    top_k_fusion = config.get("kb_fusion_top_k", 20)
    if not kb_names:
        return None

    logger.debug(f"[知识库] 开始检索知识库，数量: {len(kb_names)}, top_k={top_k}")
    kb_context = await kb_mgr.retrieve(
        query=query,
        kb_names=kb_names,
        kb_ids=kb_ids,
        top_k_fusion=top_k_fusion,
        top_m_final=top_k,
    )
    if not kb_context:
        return None

    formatted = kb_context.get("context_text", "")
    if formatted:
        results = kb_context.get("results", [])
        logger.debug(f"[知识库] 为会话 {umo} 注入了 {len(results)} 条相关知识块")
        return formatted
    return None


@builtin_tool(config=_KNOWLEDGE_BASE_TOOL_CONFIG)
@dataclass
class KnowledgeBaseQueryTool(FunctionTool[AstrAgentContext]):
    name: str = "astr_kb_search"
    description: str = (
        "Query the knowledge base for facts or relevant context. "
        "Use this tool when the user's question requires factual information, "
        "definitions, background knowledge, or previously indexed content. "
        "Only send short keywords or a concise question as the query."
    )
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "A concise keyword query for the knowledge base.",
                },
            },
            "required": ["query"],
        }
    )

    async def call(
        self, context: ContextWrapper[AstrAgentContext], **kwargs
    ) -> ToolExecResult:
        query = kwargs.get("query", "")
        if not query:
            return "error: Query parameter is empty."
        result = await retrieve_knowledge_base(
            query=query,
            umo=context.context.event.unified_msg_origin,
            context=context.context.context,
        )
        if not result:
            return "No relevant knowledge found."
        return result


@builtin_tool(config=_KNOWLEDGE_BASE_TOOL_CONFIG)
@dataclass
class KnowledgeBaseListPagesTool(FunctionTool[AstrAgentContext]):
    name: str = "astr_kb_list_pages"
    description: str = (
        "List Markdown Wiki pages and their exact paths in a knowledge base. "
        "Use this before reading, editing, or deleting a page when its path is "
        "not already known. Only administrators can use this management tool."
    )
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Optional case-insensitive filter matched against page "
                        "path, title, summary, and source."
                    ),
                },
                "knowledge_base": {
                    "type": "string",
                    "description": (
                        "Target knowledge base name or stable ID. Omit only when "
                        "the current session resolves to exactly one knowledge base."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum pages to return, from 1 to 200.",
                    "default": 50,
                },
            },
        }
    )

    async def call(
        self, context: ContextWrapper[AstrAgentContext], **kwargs
    ) -> ToolExecResult:
        """List manageable Wiki pages for the current administrator.

        Args:
            context: Current agent execution context.
            **kwargs: Tool arguments containing the target and optional filter.

        Returns:
            A compact newline-delimited page list or a user-facing error.
        """
        event = context.context.event
        plugin_context = context.context.context
        if getattr(event, "role", None) != "admin":
            return "error: Only administrators can list knowledge base pages."

        selector = str(kwargs.get("knowledge_base") or "").strip()
        kb_helper, error = await _resolve_target_knowledge_base(
            event,
            plugin_context,
            selector,
        )
        if error:
            return error
        if kb_helper is None:
            return "error: Knowledge base could not be resolved."

        try:
            wiki_store = await kb_helper._ensure_vec_db()
            tree_result = await wiki_store.list_tree()
        except Exception as exc:
            logger.error(
                "Failed to list Wiki pages for knowledge base %s: %s",
                kb_helper.kb.kb_id,
                exc,
                exc_info=True,
            )
            return f"error: Knowledge page listing failed: {str(exc).strip() or 'Unknown error'}"

        pages = []
        stack = list(reversed(tree_result.get("tree", {}).get("children", [])))
        while stack:
            entry = stack.pop()
            if entry.get("type") == "directory":
                stack.extend(reversed(entry.get("children", [])))
            elif entry.get("type") == "page":
                pages.append(entry)

        query = str(kwargs.get("query") or "").strip().casefold()
        if query:
            pages = [
                page
                for page in pages
                if query
                in " ".join(
                    str(page.get(field) or "")
                    for field in ("path", "title", "summary", "source")
                ).casefold()
            ]
        try:
            limit = max(1, min(int(kwargs.get("limit", 50)), 200))
        except (TypeError, ValueError):
            limit = 50
        selected_pages = pages[:limit]
        if not selected_pages:
            return f"No matching Wiki pages found in {kb_helper.kb.kb_name}."

        lines = []
        for page in selected_pages:
            summary = " ".join(str(page.get("summary") or "").split())
            summary_text = f" | {summary[:160]}" if summary else ""
            lines.append(
                f"- {page.get('path')} | {page.get('title') or page.get('name')}"
                f" | type={page.get('node_type') or 'other'}{summary_text}"
            )
        remaining = len(pages) - len(selected_pages)
        suffix = f"\n... {remaining} more matching pages." if remaining > 0 else ""
        return (
            f"Wiki pages in {kb_helper.kb.kb_name} ({len(pages)} matched):\n"
            + "\n".join(lines)
            + suffix
        )


@builtin_tool(config=_KNOWLEDGE_BASE_TOOL_CONFIG)
@dataclass
class KnowledgeBaseReadPageTool(FunctionTool[AstrAgentContext]):
    name: str = "astr_kb_read_page"
    description: str = (
        "Read the complete Markdown content of one Wiki page by its exact path. "
        "Use astr_kb_list_pages first if the path is unknown. Only administrators "
        "can use this management tool."
    )
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Exact Wiki-relative Markdown path.",
                },
                "knowledge_base": {
                    "type": "string",
                    "description": (
                        "Target knowledge base name or stable ID. Omit only when "
                        "the current session resolves to exactly one knowledge base."
                    ),
                },
            },
            "required": ["path"],
        }
    )

    async def call(
        self, context: ContextWrapper[AstrAgentContext], **kwargs
    ) -> ToolExecResult:
        """Read one Wiki page for a management operation.

        Args:
            context: Current agent execution context.
            **kwargs: Tool arguments containing the target page path.

        Returns:
            Complete Markdown content plus metadata or a user-facing error.
        """
        event = context.context.event
        plugin_context = context.context.context
        if getattr(event, "role", None) != "admin":
            return "error: Only administrators can read managed knowledge pages."

        path = str(kwargs.get("path") or "").strip()
        if not path:
            return "error: Wiki page path is empty."
        selector = str(kwargs.get("knowledge_base") or "").strip()
        kb_helper, error = await _resolve_target_knowledge_base(
            event,
            plugin_context,
            selector,
        )
        if error:
            return error
        if kb_helper is None:
            return "error: Knowledge base could not be resolved."

        try:
            wiki_store = await kb_helper._ensure_vec_db()
            page = await wiki_store.read_page(path)
        except FileNotFoundError:
            return f"error: Wiki page {path!r} does not exist."
        except Exception as exc:
            logger.error(
                "Failed to read Wiki page %s from knowledge base %s: %s",
                path,
                kb_helper.kb.kb_id,
                exc,
                exc_info=True,
            )
            return f"error: Knowledge page read failed: {str(exc).strip() or 'Unknown error'}"

        metadata = page.get("metadata", {})
        return (
            f"Knowledge base: {kb_helper.kb.kb_name} ({kb_helper.kb.kb_id})\n"
            f"Path: {page.get('path', path)}\n"
            f"Title: {metadata.get('title') or ''}\n"
            f"Source: {metadata.get('source') or ''}\n"
            "Markdown content:\n"
            f"{page.get('content', '')}"
        )


@builtin_tool(config=_KNOWLEDGE_BASE_TOOL_CONFIG)
@dataclass
class KnowledgeBaseEditPageTool(FunctionTool[AstrAgentContext]):
    name: str = "astr_kb_edit_page"
    description: str = (
        "Edit an existing Markdown Wiki page and rebuild its keyword index, "
        "knowledge graph links, and optional vectors. Prefer exact old_text to "
        "replacement edits so the rest of the page remains unchanged. Use "
        "full_content only when the administrator explicitly requests a complete "
        "rewrite. No Embedding Provider is required."
    )
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Exact Wiki-relative Markdown path.",
                },
                "old_text": {
                    "type": "string",
                    "description": (
                        "Exact unique text to replace. Read the page first and "
                        "include enough surrounding text to make it unique."
                    ),
                },
                "replacement": {
                    "type": "string",
                    "description": (
                        "Replacement text. May be empty to remove old_text."
                    ),
                },
                "full_content": {
                    "type": "string",
                    "description": (
                        "Complete replacement Markdown. Do not combine with "
                        "old_text/replacement."
                    ),
                },
                "knowledge_base": {
                    "type": "string",
                    "description": (
                        "Target knowledge base name or stable ID. Omit only when "
                        "the current session resolves to exactly one knowledge base."
                    ),
                },
            },
            "required": ["path"],
        }
    )

    async def call(
        self, context: ContextWrapper[AstrAgentContext], **kwargs
    ) -> ToolExecResult:
        """Edit one Wiki page and synchronize all derived metadata.

        Args:
            context: Current agent execution context.
            **kwargs: Tool arguments selecting partial or complete replacement.

        Returns:
            Updated page metadata or a user-facing error.
        """
        event = context.context.event
        plugin_context = context.context.context
        if getattr(event, "role", None) != "admin":
            return "error: Only administrators can edit knowledge base pages."

        path = str(kwargs.get("path") or "").strip()
        if not path:
            return "error: Wiki page path is empty."
        full_content_value = kwargs.get("full_content")
        old_text_value = kwargs.get("old_text")
        has_full_content = full_content_value is not None
        has_partial_edit = old_text_value is not None or "replacement" in kwargs
        if has_full_content and has_partial_edit:
            return "error: Use either full_content or old_text/replacement, not both."
        if not has_full_content and not has_partial_edit:
            return "error: Provide full_content or an old_text/replacement edit."
        if has_partial_edit and (old_text_value is None or "replacement" not in kwargs):
            return (
                "error: Both old_text and replacement are required for a partial edit."
            )

        selector = str(kwargs.get("knowledge_base") or "").strip()
        kb_helper, error = await _resolve_target_knowledge_base(
            event,
            plugin_context,
            selector,
        )
        if error:
            return error
        if kb_helper is None:
            return "error: Knowledge base could not be resolved."

        try:
            wiki_store = await kb_helper._ensure_vec_db()
            existing_page = await wiki_store.read_page(path)
            existing_content = existing_page.get("content", "")
            if has_full_content:
                updated_content = str(full_content_value or "").strip()
                if not updated_content:
                    return "error: full_content cannot be empty."
            else:
                old_text = str(old_text_value)
                if not old_text:
                    return "error: old_text cannot be empty."
                replacement = str(kwargs.get("replacement") or "")
                occurrence_count = existing_content.count(old_text)
                if occurrence_count != 1:
                    return (
                        "error: old_text must match exactly once; "
                        f"found {occurrence_count} matches."
                    )
                updated_content = existing_content.replace(old_text, replacement, 1)
            if updated_content == existing_content:
                return "error: The requested edit does not change the page."

            existing_doc_id = existing_page.get("metadata", {}).get("doc_id")
            updated_page = await wiki_store.write_page(
                path,
                updated_content,
                doc_id=existing_doc_id,
                require_existing=True,
            )

            document = await kb_helper.get_document(updated_page["doc_id"])
            if document is None:
                document = KBDocument(
                    doc_id=updated_page["doc_id"],
                    kb_id=kb_helper.kb.kb_id,
                    doc_name=updated_page["title"],
                    file_type="md",
                    file_size=len(updated_content.encode("utf-8")),
                    file_path=updated_page["path"],
                    chunk_count=updated_page["chunk_count"],
                    media_count=0,
                )
            else:
                document.doc_name = updated_page["title"]
                document.file_size = len(updated_content.encode("utf-8"))
                document.file_path = updated_page["path"]
                document.chunk_count = updated_page["chunk_count"]
            kb_manager = plugin_context.kb_manager
            async with kb_manager.kb_db.get_db() as session, session.begin():
                session.add(document)
            await kb_manager.kb_db.update_kb_stats(
                kb_id=kb_helper.kb.kb_id,
                vec_db=wiki_store,
            )
            await kb_helper.refresh_kb()
        except FileNotFoundError:
            return f"error: Wiki page {path!r} does not exist."
        except Exception as exc:
            logger.error(
                "Failed to edit Wiki page %s in knowledge base %s: %s",
                path,
                kb_helper.kb.kb_id,
                exc,
                exc_info=True,
            )
            return f"error: Knowledge page edit failed: {str(exc).strip() or 'Unknown error'}"

        embedding_provider_id = getattr(
            kb_helper.kb,
            "embedding_provider_id",
            None,
        )
        index_mode = (
            "hybrid vector and keyword indexing"
            if embedding_provider_id
            else "keyword indexing; no Embedding Provider required"
        )
        return (
            f"Updated Wiki page {updated_page['path']} in {kb_helper.kb.kb_name}. "
            f"Title: {updated_page['title']}. Chunks: {updated_page['chunk_count']}. "
            f"Index mode: {index_mode}."
        )


@builtin_tool(config=_KNOWLEDGE_BASE_TOOL_CONFIG)
@dataclass
class KnowledgeBaseDeletePageTool(FunctionTool[AstrAgentContext]):
    name: str = "astr_kb_delete_page"
    description: str = (
        "Delete exactly one Markdown Wiki page and its derived chunks, graph node, "
        "links, and optional vectors. Use only after the administrator explicitly "
        "requests deletion and the exact path has been verified with list/read. "
        "This tool cannot delete an entire knowledge base or a directory."
    )
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Exact Wiki-relative Markdown path to delete.",
                },
                "expected_title": {
                    "type": "string",
                    "description": (
                        "Exact page title returned by astr_kb_list_pages or "
                        "astr_kb_read_page. Deletion stops if it does not match."
                    ),
                },
                "confirm": {
                    "type": "boolean",
                    "description": (
                        "Must be true only after the administrator explicitly "
                        "confirmed deletion of this exact page."
                    ),
                },
                "knowledge_base": {
                    "type": "string",
                    "description": (
                        "Target knowledge base name or stable ID. Omit only when "
                        "the current session resolves to exactly one knowledge base."
                    ),
                },
            },
            "required": ["path", "expected_title", "confirm"],
        }
    )

    async def call(
        self, context: ContextWrapper[AstrAgentContext], **kwargs
    ) -> ToolExecResult:
        """Delete one explicitly confirmed Wiki page.

        Args:
            context: Current agent execution context.
            **kwargs: Tool arguments containing the exact path and confirmation.

        Returns:
            A deletion confirmation or a user-facing error.
        """
        event = context.context.event
        plugin_context = context.context.context
        if getattr(event, "role", None) != "admin":
            return "error: Only administrators can delete knowledge base pages."
        if kwargs.get("confirm") is not True:
            return "error: Explicit deletion confirmation is required."

        path = str(kwargs.get("path") or "").strip()
        if not path:
            return "error: Wiki page path is empty."
        expected_title = " ".join(
            str(kwargs.get("expected_title") or "").split()
        ).strip()
        if not expected_title:
            return "error: Exact expected_title is required for deletion."
        selector = str(kwargs.get("knowledge_base") or "").strip()
        kb_helper, error = await _resolve_target_knowledge_base(
            event,
            plugin_context,
            selector,
        )
        if error:
            return error
        if kb_helper is None:
            return "error: Knowledge base could not be resolved."

        try:
            wiki_store = await kb_helper._ensure_vec_db()
            page = await wiki_store.get_page_metadata(path)
            if not page:
                return f"error: Wiki page {path!r} does not exist."
            actual_title = " ".join(str(page.get("title") or "").split()).strip()
            if actual_title != expected_title:
                return (
                    "error: Page title confirmation does not match; "
                    f"expected {expected_title!r}, actual {actual_title!r}."
                )
            document = await kb_helper.get_document(page["doc_id"])
            if document is not None:
                await kb_helper.delete_document(page["doc_id"])
            else:
                deleted = await wiki_store.delete_page(path)
                if not deleted:
                    return f"error: Wiki page {path!r} does not exist."
                kb_manager = plugin_context.kb_manager
                await kb_manager.kb_db.update_kb_stats(
                    kb_id=kb_helper.kb.kb_id,
                    vec_db=wiki_store,
                )
                await kb_helper.refresh_kb()
        except Exception as exc:
            logger.error(
                "Failed to delete Wiki page %s from knowledge base %s: %s",
                path,
                kb_helper.kb.kb_id,
                exc,
                exc_info=True,
            )
            return f"error: Knowledge page deletion failed: {str(exc).strip() or 'Unknown error'}"

        return (
            f"Deleted Wiki page {path} from {kb_helper.kb.kb_name} "
            f"({kb_helper.kb.kb_id})."
        )


@builtin_tool(config=_KNOWLEDGE_BASE_TOOL_CONFIG)
@dataclass
class KnowledgeBaseWritePageTool(FunctionTool[AstrAgentContext]):
    name: str = "astr_kb_save_text"
    description: str = (
        "Save extracted web article content, notes, or other supplied text as a "
        "Markdown Wiki page in a knowledge base. Use this after opening a link "
        "with browser or OpenCLI when an administrator asks to save the content. "
        "An Embedding Provider is NOT required: Markdown storage and keyword "
        "indexing always work, and vector indexing is added only when configured. "
        "Never ask the user for an embedding API key before using this tool."
    )
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Page or article title.",
                },
                "content": {
                    "type": "string",
                    "description": (
                        "Complete extracted article or note content in Markdown "
                        "or plain text."
                    ),
                },
                "source": {
                    "type": "string",
                    "description": "Optional source URL or provenance label.",
                },
                "knowledge_base": {
                    "type": "string",
                    "description": (
                        "Target knowledge base name or stable ID. Omit only when "
                        "the current session resolves to exactly one knowledge base."
                    ),
                },
            },
            "required": ["title", "content"],
        }
    )

    async def call(
        self, context: ContextWrapper[AstrAgentContext], **kwargs
    ) -> ToolExecResult:
        event = context.context.event
        plugin_context = context.context.context
        if event.role != "admin":
            return "error: Only administrators can save knowledge base pages."

        title = " ".join(str(kwargs.get("title") or "").split()).strip()
        content = str(kwargs.get("content") or "").strip()
        source = " ".join(str(kwargs.get("source") or "").split()).strip()
        if not title:
            return "error: Page title is empty."
        if not content:
            return "error: Page content is empty."

        selector = str(kwargs.get("knowledge_base") or "").strip()
        kb_helper, error = await _resolve_target_knowledge_base(
            event,
            plugin_context,
            selector,
        )
        if error:
            return error
        if kb_helper is None:
            return "error: Knowledge base could not be resolved."

        file_stem = re.sub(r"[\x00-\x1f/\\]+", " ", title).strip(" .")
        file_name = f"{(file_stem or 'knowledge-page')[:180]}.md"
        chunk_size = getattr(kb_helper.kb, "chunk_size", None)
        chunk_overlap = getattr(kb_helper.kb, "chunk_overlap", None)
        try:
            document = await kb_helper.upload_document(
                file_name=file_name,
                file_content=content.encode("utf-8"),
                file_type="md",
                chunk_size=(
                    chunk_size if chunk_size is not None else DEFAULT_CHUNK_SIZE
                ),
                chunk_overlap=(
                    chunk_overlap
                    if chunk_overlap is not None
                    else DEFAULT_CHUNK_OVERLAP
                ),
                source_label=source or title,
            )
        except Exception as exc:
            logger.error(
                "Failed to save extracted text to knowledge base %s: %s",
                kb_helper.kb.kb_id,
                exc,
                exc_info=True,
            )
            error_message = str(exc).strip() or "Unknown save error"
            return f"error: Knowledge save failed: {error_message}"

        embedding_provider_id = getattr(
            kb_helper.kb,
            "embedding_provider_id",
            None,
        )
        index_mode = (
            "hybrid vector and keyword indexing"
            if embedding_provider_id
            else "keyword indexing; no Embedding Provider required"
        )
        return (
            f"Saved Wiki page to {kb_helper.kb.kb_name} "
            f"({kb_helper.kb.kb_id}). Path: {document.file_path}. "
            f"Chunks: {document.chunk_count}. Index mode: {index_mode}."
        )


@builtin_tool(config=_KNOWLEDGE_BASE_TOOL_CONFIG)
@dataclass
class KnowledgeBaseExportTool(FunctionTool[AstrAgentContext]):
    name: str = "astr_kb_export"
    description: str = (
        "Export one knowledge base as a ZIP attachment containing its Markdown "
        "Wiki pages. Folder paths are preserved exactly relative to the knowledge "
        "root. Use this when an administrator asks to download, export, or back up "
        "a knowledge base. The ZIP is sent directly to the current conversation."
    )
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "knowledge_base": {
                    "type": "string",
                    "description": (
                        "Target knowledge base name or stable ID. Omit only when "
                        "the current session resolves to exactly one knowledge base."
                    ),
                },
            },
        }
    )

    async def call(
        self, context: ContextWrapper[AstrAgentContext], **kwargs
    ) -> ToolExecResult | MessageEventResult:
        """Create and send one knowledge base Wiki archive.

        Args:
            context: Current agent execution context and platform event.
            **kwargs: Tool arguments containing the optional knowledge base
                selector.

        Returns:
            A direct file message result or a user-facing error string.
        """
        event = context.context.event
        plugin_context = context.context.context
        if event.role != "admin":
            return "error: Only administrators can export knowledge bases."

        selector = str(kwargs.get("knowledge_base") or "").strip()
        kb_helper, error = await _resolve_target_knowledge_base(
            event,
            plugin_context,
            selector,
        )
        if error:
            return error
        if kb_helper is None:
            return "error: Knowledge base could not be resolved."

        try:
            archive_path, filename, page_count = await asyncio.to_thread(
                kb_helper.export_wiki_archive
            )
        except Exception as exc:
            logger.error(
                "Failed to export knowledge base %s: %s",
                kb_helper.kb.kb_id,
                exc,
                exc_info=True,
            )
            return (
                f"error: Knowledge export failed: {str(exc).strip() or 'Unknown error'}"
            )

        event.track_temporary_local_file(str(archive_path))
        result = MessageEventResult().message(
            f"Exported {page_count} Markdown pages from "
            f"{kb_helper.kb.kb_name} ({kb_helper.kb.kb_id})."
        )
        result.chain.append(File(name=filename, file=str(archive_path)))
        return result


@builtin_tool(config=_KNOWLEDGE_BASE_TOOL_CONFIG)
@dataclass
class KnowledgeBaseImportAttachmentTool(FunctionTool[AstrAgentContext]):
    name: str = "astr_kb_import_attachment"
    description: str = (
        "Import a Markdown file or ZIP attachment from the current or quoted "
        "message into a knowledge base while preserving its folder structure. "
        "Use this only when an administrator explicitly asks to save or import "
        "the attached knowledge files."
    )
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "attachment_name": {
                    "type": "string",
                    "description": (
                        "Exact attachment filename. Omit only when the message "
                        "contains exactly one file attachment."
                    ),
                },
                "knowledge_base": {
                    "type": "string",
                    "description": (
                        "Target knowledge base name or stable ID. Omit only when "
                        "the current session resolves to exactly one knowledge base."
                    ),
                },
                "overwrite": {
                    "type": "boolean",
                    "description": (
                        "Replace pages with identical paths. Defaults to false; "
                        "enable only when the user explicitly requests replacement."
                    ),
                    "default": False,
                },
            },
        }
    )

    async def call(
        self, context: ContextWrapper[AstrAgentContext], **kwargs
    ) -> ToolExecResult:
        event = context.context.event
        plugin_context = context.context.context
        if event.role != "admin":
            return "error: Only administrators can import knowledge base attachments."

        attachments: list[File] = []
        for component in event.message_obj.message:
            if isinstance(component, File):
                attachments.append(component)
            elif isinstance(component, Reply) and component.chain:
                attachments.extend(
                    item for item in component.chain if isinstance(item, File)
                )
        if not attachments:
            return (
                "error: No file attachment was found in the current or quoted "
                "message. Reply to the attachment and try again."
            )

        requested_name = str(kwargs.get("attachment_name") or "").strip()
        if requested_name:
            matching = [
                attachment
                for attachment in attachments
                if (attachment.name or "").casefold() == requested_name.casefold()
            ]
            if len(matching) != 1:
                available = ", ".join(
                    attachment.name or "unnamed" for attachment in attachments
                )
                return (
                    f"error: Attachment {requested_name!r} is missing or ambiguous. "
                    f"Available attachments: {available}"
                )
            attachment = matching[0]
        elif len(attachments) == 1:
            attachment = attachments[0]
        else:
            available = ", ".join(
                attachment.name or "unnamed" for attachment in attachments
            )
            return f"error: Multiple attachments found; specify one of: {available}"

        attachment_name = Path(
            str(attachment.name or "knowledge.zip").replace("\\", "/")
        ).name
        attachment_name = attachment_name or "knowledge.zip"
        if Path(attachment_name).suffix.lower() not in {
            ".md",
            ".markdown",
            ".mdx",
            ".zip",
        }:
            return "error: Only Markdown files and ZIP archives are supported."

        selector = str(kwargs.get("knowledge_base") or "").strip()
        kb_helper, error = await _resolve_target_knowledge_base(
            event,
            plugin_context,
            selector,
        )
        if error:
            return error
        if kb_helper is None:
            return "error: Knowledge base could not be resolved."

        file_path = await attachment.get_file()
        if not file_path or not Path(file_path).is_file():
            return "error: The attachment could not be downloaded to a local file."

        target_path = (
            None if Path(attachment_name).suffix.lower() == ".zip" else attachment_name
        )
        try:
            result = await kb_helper.import_wiki_sources(
                [(Path(file_path), target_path)],
                overwrite=bool(kwargs.get("overwrite", False)),
            )
        except Exception as exc:
            logger.error(
                "Failed to import knowledge attachment %s: %s",
                attachment_name,
                exc,
                exc_info=True,
            )
            error_message = str(exc).strip() or "Unknown import error"
            for local_path in {file_path, str(Path(file_path).resolve())}:
                if local_path:
                    error_message = error_message.replace(local_path, attachment_name)
            return f"error: Knowledge import failed: {error_message}"

        imported = result.get("imported", [])
        imported_paths = [str(page.get("path", "")) for page in imported]
        preview = ", ".join(path for path in imported_paths[:20] if path)
        if len(imported_paths) > 20:
            preview += f", ... and {len(imported_paths) - 20} more"
        skipped = result.get("skipped", [])
        skipped_text = f" Skipped {len(skipped)} entries." if skipped else ""
        return (
            f"Imported {len(imported)} Wiki pages into "
            f"{kb_helper.kb.kb_name} ({kb_helper.kb.kb_id})."
            f"{skipped_text} Paths: {preview or 'none'}"
        )


__all__ = [
    "KnowledgeBaseDeletePageTool",
    "KnowledgeBaseEditPageTool",
    "KnowledgeBaseImportAttachmentTool",
    "KnowledgeBaseListPagesTool",
    "KnowledgeBaseQueryTool",
    "KnowledgeBaseReadPageTool",
    "KnowledgeBaseWritePageTool",
    "retrieve_knowledge_base",
]
