import ast
import re
from pathlib import Path

import frappe
from frappe.tests.utils import FrappeTestCase


APP_PATH = Path(frappe.get_app_path("slow_ai"))
API_DIR = APP_PATH / "api"
DOCTYPE_DIR = APP_PATH / "slow_ai" / "doctype"
CLIENT_DIRS = (
    APP_PATH / "public",
    APP_PATH / "www",
    APP_PATH / "templates",
    APP_PATH / "slow_ai" / "page",
)
PRODUCTION_DIRS = (
    APP_PATH / "api",
    APP_PATH / "application",
    APP_PATH / "domain",
    APP_PATH / "engine",
    APP_PATH / "infrastructure",
    APP_PATH / "node_registry",
    APP_PATH / "providers",
    APP_PATH / "workers",
    APP_PATH / "slow_ai" / "doctype",
    APP_PATH / "slow_ai" / "page",
)

API_ALLOWED_CLIENT_METHODS = {
    "slow_ai.api.assets.upload",
    "slow_ai.api.assets.view",
    "slow_ai.api.models.get_model",
    "slow_ai.api.models.get_model_metadata",
    "slow_ai.api.models.list_models",
    "slow_ai.api.models.update_model_metadata",
    "slow_ai.api.models.update_model_pricing",
    "slow_ai.api.models.update_model_status",
    "slow_ai.api.nodes.get_object_info",
    "slow_ai.api.billing.get_balance",
    "slow_ai.api.provider_accounts.list_accounts",
    "slow_ai.api.provider_accounts.get_account",
    "slow_ai.api.provider_accounts.create_account",
    "slow_ai.api.provider_accounts.set_default",
    "slow_ai.api.provider_accounts.disable_account",
    "slow_ai.api.projects.list_my_projects",
    "slow_ai.api.projects.list_members",
    "slow_ai.api.projects.add_member",
    "slow_ai.api.projects.update_member_role",
    "slow_ai.api.projects.disable_member",
    "slow_ai.api.public_tools.list_templates",
    "slow_ai.api.public_tools.get_template",
    "slow_ai.api.public_tools.create_workflow_from_template",
    "slow_ai.api.public_tools.prepare_workflow_from_template",
    "slow_ai.api.public_tools.list_my_runs",
    "slow_ai.api.public_tools.get_my_run",
    "slow_ai.api.public_tools.get_run_output_gallery",
    "slow_ai.api.public_tools.create_run_share",
    "slow_ai.api.public_tools.disable_run_share",
    "slow_ai.api.public_tools.get_shared_run",
    "slow_ai.api.queue.get_queue_status",
    "slow_ai.api.runs.start_run",
    "slow_ai.api.runs.get_run_status",
    "slow_ai.api.runs.get_history",
    "slow_ai.api.templates.save_template",
    "slow_ai.api.templates.get_template",
    "slow_ai.api.templates.list_templates",
    "slow_ai.api.templates.create_workflow_from_template",
    "slow_ai.api.templates.submit_template_for_review",
    "slow_ai.api.templates.approve_template",
    "slow_ai.api.templates.reject_template",
    "slow_ai.api.templates.archive_template",
    "slow_ai.api.workflows.save_workflow",
    "slow_ai.api.workflows.get_workflow",
}

API_FORBIDDEN_IMPORT_PREFIXES = (
    "slow_ai.engine",
    "slow_ai.node_registry",
    "slow_ai.providers",
    "slow_ai.infrastructure",
    "slow_ai.workers",
    "slow_ai.slow_ai.doctype",
)
API_FORBIDDEN_FRAGMENTS = (
    "frappe.db",
    "frappe.get_doc",
    "frappe.enqueue",
    "WorkflowExecutor",
    "ProviderAdapter",
    "ProviderRegistry",
    "AIProviderJob",
    "AICreditLedger",
)
DOCTYPE_FORBIDDEN_IMPORT_PREFIXES = (
    "slow_ai.api",
    "slow_ai.application",
    "slow_ai.domain",
    "slow_ai.engine",
    "slow_ai.infrastructure",
    "slow_ai.node_registry",
    "slow_ai.providers",
    "slow_ai.workers",
)
DOCTYPE_FORBIDDEN_FRAGMENTS = (
    "frappe.enqueue",
    "frappe.db.sql",
    "WorkflowExecutor",
    "ProviderAdapter",
    "ProviderRegistry",
    "submit_job",
    "poll_job",
    "run_workflow",
)
CLIENT_FORBIDDEN_FRAGMENTS = (
    "WAVESPEED_API_KEY",
    "api_key_secret",
    "Authorization: Bearer",
    "ProviderAdapter",
    "ProviderRegistry",
    "WorkflowExecutor",
    "AI Provider Job",
    "AI Credit Ledger",
    "frappe.db",
    "run_workflow",
    "submit_job",
    "poll_job",
)
LOCAL_RUNTIME_FORBIDDEN_PATTERNS = (
    r"\bcheckpoint\b",
    r"\bclip loader\b",
    r"\bvae loader\b",
    r"\bksampler\b",
    r"\bcuda\b",
    r"\bgpu\b",
    r"\blocal model\b",
    r"\blocal_model\b",
    r"\bmodel folder\b",
    r"\btorch\b",
    r"\btensorflow\b",
    r"\bdiffusers\b",
    r"\bsafetensors\b",
    r"\bckpt\b",
)
LOCAL_RUNTIME_ALLOWLIST = {
    APP_PATH / "node_registry" / "registry.py",
}


def python_files(root: Path):
    return sorted(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)


def text_files(root: Path):
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix in {".css", ".html", ".js", ".json", ".py", ".txt"}
    )


def parse_python(path: Path) -> ast.Module:
    return ast.parse(path.read_text(), filename=str(path))


def imported_modules(tree: ast.Module) -> set[str]:
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        if isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def is_whitelisted_function(node: ast.FunctionDef) -> bool:
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if (
            isinstance(target, ast.Attribute)
            and target.attr == "whitelist"
            and isinstance(target.value, ast.Name)
            and target.value.id == "frappe"
        ):
            return True
    return False


def returned_call_name(node: ast.Return) -> str | None:
    value = node.value
    if isinstance(value, ast.Call):
        func = value.func
        if isinstance(func, ast.Name):
            return func.id
        if isinstance(func, ast.Attribute):
            return func.attr
    return None


def executable_statements(function: ast.FunctionDef) -> list[ast.stmt]:
    body = list(function.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    return body


class TestArchitectureBoundaries(FrappeTestCase):
    def test_api_methods_are_thin_application_delegates(self):
        failures = []
        for path in python_files(API_DIR):
            if path.name == "__init__.py":
                continue
            source = path.read_text()
            tree = parse_python(path)
            imports = imported_modules(tree)
            invalid_imports = sorted(
                name
                for name in imports
                if any(name == prefix or name.startswith(f"{prefix}.") for prefix in API_FORBIDDEN_IMPORT_PREFIXES)
            )
            if invalid_imports:
                failures.append(f"{path.relative_to(APP_PATH)} imports {invalid_imports}")

            forbidden = [fragment for fragment in API_FORBIDDEN_FRAGMENTS if fragment in source]
            if forbidden:
                failures.append(f"{path.relative_to(APP_PATH)} contains {forbidden}")

            for node in tree.body:
                if not isinstance(node, ast.FunctionDef) or not is_whitelisted_function(node):
                    continue
                executable = executable_statements(node)
                if len(executable) != 1 or not isinstance(executable[0], ast.Return):
                    failures.append(f"{path.relative_to(APP_PATH)}:{node.name} is not a single return delegate")
                    continue
                call_name = returned_call_name(executable[0])
                if not call_name or not call_name.endswith("_service"):
                    failures.append(f"{path.relative_to(APP_PATH)}:{node.name} does not return an application service call")

        self.assertEqual([], failures)

    def test_doctype_controllers_remain_persistence_only(self):
        failures = []
        for path in python_files(DOCTYPE_DIR):
            if path.name == "__init__.py":
                continue
            source = path.read_text()
            tree = parse_python(path)
            imports = imported_modules(tree)
            invalid_imports = sorted(
                name
                for name in imports
                if any(name == prefix or name.startswith(f"{prefix}.") for prefix in DOCTYPE_FORBIDDEN_IMPORT_PREFIXES)
            )
            if invalid_imports:
                failures.append(f"{path.relative_to(APP_PATH)} imports {invalid_imports}")
            forbidden = [fragment for fragment in DOCTYPE_FORBIDDEN_FRAGMENTS if fragment in source]
            if forbidden:
                failures.append(f"{path.relative_to(APP_PATH)} contains {forbidden}")

        self.assertEqual([], failures)

    def test_client_assets_call_only_server_api_methods(self):
        failures = []
        method_pattern = re.compile(r"frappe\.call\(\s*[\"']([^\"']+)[\"']")
        for root in CLIENT_DIRS:
            if not root.exists():
                continue
            for path in text_files(root):
                source = path.read_text()
                forbidden = [fragment for fragment in CLIENT_FORBIDDEN_FRAGMENTS if fragment in source]
                if forbidden:
                    failures.append(f"{path.relative_to(APP_PATH)} contains {forbidden}")
                if "frappe.xcall" in source:
                    failures.append(f"{path.relative_to(APP_PATH)} uses frappe.xcall")
                for method in method_pattern.findall(source):
                    if method.startswith("slow_ai.") and method not in API_ALLOWED_CLIENT_METHODS:
                        failures.append(f"{path.relative_to(APP_PATH)} calls unapproved API method {method}")

        self.assertEqual([], failures)

    def test_no_local_model_runtime_terms_in_production_code(self):
        failures = []
        pattern = re.compile("|".join(LOCAL_RUNTIME_FORBIDDEN_PATTERNS), re.IGNORECASE)
        for root in PRODUCTION_DIRS:
            for path in text_files(root):
                if path in LOCAL_RUNTIME_ALLOWLIST:
                    continue
                matches = sorted({match.group(0) for match in pattern.finditer(path.read_text())})
                if matches:
                    failures.append(f"{path.relative_to(APP_PATH)} contains local runtime terms {matches}")

        self.assertEqual([], failures)

    def test_production_code_does_not_reference_comfyui(self):
        failures = []
        for root in PRODUCTION_DIRS:
            for path in text_files(root):
                if "comfyui" in path.read_text().lower():
                    failures.append(str(path.relative_to(APP_PATH)))

        self.assertEqual([], failures)

    def test_direct_sql_is_not_used_in_slow_ai_layers(self):
        failures = []
        for root in PRODUCTION_DIRS:
            for path in text_files(root):
                if "frappe.db.sql" in path.read_text():
                    failures.append(str(path.relative_to(APP_PATH)))

        self.assertEqual([], failures)
