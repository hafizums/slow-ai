"""Frappe Desk workspace setup for slow_ai."""

from __future__ import annotations

import json

import frappe


WORKSPACE_TITLE = "Slow AI"
WORKSPACE_MODULE = "Slow Ai"
WORKSPACE_ICON = "image"
WORKSPACE_PAGE = "slow-ai-canvas"


def sync_private_workspaces() -> None:
    """Create or update the private Slow AI workspace for existing system users."""

    for user in _system_users():
        sync_private_workspace_for_user(user)


def sync_private_workspace_on_login(login_manager=None) -> None:
    """Create or update the private Slow AI workspace for the logging-in user."""

    user = getattr(login_manager, "user", None) or frappe.session.user
    if _is_system_user(user):
        sync_private_workspace_for_user(user)


def sync_private_workspace_for_user(user: str) -> str:
    """Create or update one user's private Slow AI workspace."""

    if not user or not _is_system_user(user):
        return ""

    workspace_name = _workspace_name(user)
    if frappe.db.exists("Workspace", workspace_name):
        workspace = frappe.get_doc("Workspace", workspace_name)
    else:
        workspace = frappe.new_doc("Workspace")
        workspace.name = workspace_name
        workspace.label = workspace_name

    workspace.title = WORKSPACE_TITLE
    workspace.module = WORKSPACE_MODULE
    workspace.icon = WORKSPACE_ICON
    workspace.public = 0
    workspace.for_user = user
    workspace.parent_page = ""
    workspace.is_hidden = 0
    workspace.hide_custom = 1
    workspace.content = json.dumps(_workspace_content())
    workspace.set("shortcuts", _workspace_shortcuts())
    workspace.set("links", _workspace_links())
    workspace.set("charts", [])
    workspace.set("quick_lists", [])
    workspace.set("number_cards", [])
    workspace.set("custom_blocks", [])
    if not workspace.sequence_id:
        workspace.sequence_id = 1

    workspace.save(ignore_permissions=True)
    frappe.clear_cache(user=user)
    return workspace.name


def _system_users() -> list[str]:
    users = frappe.get_all(
        "User",
        fields=["name", "user_type"],
        filters={"enabled": 1},
        order_by="name asc",
    )
    return [user.name for user in users if user.name != "Guest" and user.user_type == "System User"]


def _is_system_user(user: str) -> bool:
    if user == "Guest":
        return False
    return frappe.db.get_value("User", user, "user_type") == "System User"


def _workspace_name(user: str) -> str:
    return f"{WORKSPACE_TITLE}-{user}"


def _workspace_content() -> list[dict]:
    return [
        _header("Workflow"),
        _shortcut("Canvas", 3),
        _shortcut("AI Project", 3),
        _shortcut("AI Workflow", 3),
        _shortcut("AI Workflow Run", 3),
        _spacer(),
        _header("Records"),
        _card("Create and Run", 4),
        _card("Runs", 4),
        _card("Assets and Billing", 4),
        _card("Provider Setup", 4),
    ]


def _workspace_shortcuts() -> list[dict]:
    return [
        {"label": "Canvas", "type": "Page", "link_to": WORKSPACE_PAGE},
        {"label": "AI Project", "type": "DocType", "link_to": "AI Project", "doc_view": "List"},
        {"label": "AI Workflow", "type": "DocType", "link_to": "AI Workflow", "doc_view": "List"},
        {
            "label": "AI Workflow Run",
            "type": "DocType",
            "link_to": "AI Workflow Run",
            "doc_view": "List",
        },
    ]


def _workspace_links() -> list[dict]:
    return [
        _card_break("Create and Run"),
        _link("Canvas", "Page", WORKSPACE_PAGE),
        _link("AI Project", "DocType", "AI Project"),
        _link("AI Project Member", "DocType", "AI Project Member"),
        _link("AI Workflow", "DocType", "AI Workflow"),
        _link("AI Workflow Version", "DocType", "AI Workflow Version"),
        _link("AI Workflow Template", "DocType", "AI Workflow Template"),
        _link("AI Workflow Template Version", "DocType", "AI Workflow Template Version"),
        _card_break("Runs"),
        _link("AI Workflow Run", "DocType", "AI Workflow Run"),
        _link("AI Node Run", "DocType", "AI Node Run"),
        _link("AI Provider Job", "DocType", "AI Provider Job"),
        _link("AI Tool Run Share", "DocType", "AI Tool Run Share"),
        _card_break("Assets and Billing"),
        _link("AI Asset", "DocType", "AI Asset"),
        _link("AI Credit Ledger", "DocType", "AI Credit Ledger"),
        _card_break("Provider Setup"),
        _link("AI Provider Account", "DocType", "AI Provider Account"),
        _link("AI Model", "DocType", "AI Model"),
    ]


def _header(text: str) -> dict:
    return {
        "type": "header",
        "data": {"text": f'<span class="h4"><b>{text}</b></span>', "col": 12},
    }


def _shortcut(shortcut_name: str, col: int) -> dict:
    return {"type": "shortcut", "data": {"shortcut_name": shortcut_name, "col": col}}


def _card(card_name: str, col: int) -> dict:
    return {"type": "card", "data": {"card_name": card_name, "col": col}}


def _spacer() -> dict:
    return {"type": "spacer", "data": {"col": 12}}


def _card_break(label: str) -> dict:
    return {
        "type": "Card Break",
        "label": label,
        "hidden": 0,
        "is_query_report": 0,
        "link_count": 0,
        "onboard": 0,
    }


def _link(label: str, link_type: str, link_to: str) -> dict:
    return {
        "type": "Link",
        "label": label,
        "link_type": link_type,
        "link_to": link_to,
        "dependencies": "",
        "hidden": 0,
        "is_query_report": 0,
        "link_count": 0,
        "onboard": 0,
    }
