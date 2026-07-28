from pathlib import Path

from pydantic import Field
from pydantic.dataclasses import dataclass

from astrbot.api import logger, sp
from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import FunctionTool, ToolExecResult
from astrbot.core.astr_agent_context import AstrAgentContext
from astrbot.core.message.components import File, Reply
from astrbot.core.star.context import Context
from astrbot.core.tools.registry import builtin_tool

_KNOWLEDGE_BASE_TOOL_CONFIG = {
    "kb_agentic_mode": True,
}


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

        kb_manager = plugin_context.kb_manager
        selector = str(kwargs.get("knowledge_base") or "").strip()
        kb_helper = None
        if selector:
            kb_helper = await kb_manager.get_kb(selector)
            if kb_helper is None:
                kb_helper = await kb_manager.get_kb_by_name(selector)
            if kb_helper is None:
                return f"error: Knowledge base {selector!r} does not exist."
        else:
            configured_helpers = []
            session_config = await sp.session_get(
                event.unified_msg_origin,
                "kb_config",
                default={},
            )
            has_explicit_session_selection = bool(
                session_config and "kb_ids" in session_config
            )
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
                names = ", ".join(
                    helper.kb.kb_name for helper in unique_helpers.values()
                )
                suffix = f" Current candidates: {names}." if names else ""
                return (
                    "error: Specify the target knowledge base because the current "
                    f"session does not resolve to exactly one.{suffix}"
                )
            kb_helper = next(iter(unique_helpers.values()))

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
    "KnowledgeBaseImportAttachmentTool",
    "KnowledgeBaseQueryTool",
    "retrieve_knowledge_base",
]
