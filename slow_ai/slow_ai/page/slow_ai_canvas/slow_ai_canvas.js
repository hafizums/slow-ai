frappe.pages["slow-ai-canvas"].on_page_load = function (wrapper) {
	const canvas = new SlowAiCanvasPlaceholder(wrapper);
	$(wrapper).data("slow-ai-canvas", canvas);
};

frappe.pages["slow-ai-canvas"].on_page_show = function (wrapper) {
	const canvas = $(wrapper).data("slow-ai-canvas");
	if (canvas) {
		canvas.show();
	}
};

class SlowAiCanvasPlaceholder {
	constructor(wrapper) {
		this.wrapper = wrapper;
		this.page = frappe.ui.make_app_page({
			parent: wrapper,
			title: __("Slow AI Canvas"),
			single_column: true,
		});
		this.workflow = null;
		this.workflowRun = null;
		this.objectInfo = {};
		this.templates = [];
		this.selectedTemplate = null;
		this.toolModeTemplate = null;
		this.nodeRunsByNodeId = {};
		this.pollTimer = null;
		this.nodes = this.defaultNodes();
		this.edges = this.defaultEdges();
		this.selectedNodeId = null;
		this.layout = { nodes: this.nodes.map((node) => ({ id: node.id, ...node.position })) };
		this.makeBody();
		this.makeControls();
		this.bindRealtime();
		this.render();
	}

	makeControls() {
		const controlsParent = this.$draftControls || undefined;
		this.projectField = this.page.add_field({
			label: __("Project"),
			fieldname: "project",
			fieldtype: "Link",
			options: "AI Project",
			reqd: 1,
		}, controlsParent);
		this.workflowField = this.page.add_field({
			label: __("Workflow"),
			fieldname: "workflow",
			fieldtype: "Link",
			options: "AI Workflow",
			change: () => this.loadWorkflow(),
		}, controlsParent);
		this.titleField = this.page.add_field({
			label: __("Title"),
			fieldname: "title",
			fieldtype: "Data",
			default: "Untitled AI Workflow",
		}, controlsParent);
		this.page.add_inner_button(__("Load"), () => this.loadWorkflow());
		this.page.add_inner_button(__("Save Draft"), () => this.saveWorkflow(), __("Workflow"));
		this.page.add_inner_button(__("Start Run"), () => this.startRun(), __("Workflow"));
		this.page.add_inner_button(__("Refresh Run"), () => this.refreshRun(), __("Run"));
		this.page.add_action_item(__("New Text Output Draft"), () => this.newDefaultDraft());
	}

	makeBody() {
		this.page.main.empty();
		$(frappe.render_template("slow_ai_canvas")).appendTo(this.page.main);
		this.$root = this.page.main.find("[data-page='slow-ai-canvas']");
		this.$draftControls = this.$root.find("[data-role='draft-controls']");
		this.$status = this.$root.find("[data-role='status']");
		this.$run = this.$root.find("[data-role='run']");
		this.$palette = this.$root.find("[data-role='node-palette']");
		this.$templateLibrary = this.$root.find("[data-role='template-library']");
		this.$templatePreview = this.$root.find("[data-role='template-preview']");
		this.$toolMode = this.$root.find("[data-role='tool-mode']");
		this.$stage = this.$root.find("[data-role='stage']");
		this.$edges = this.$root.find("[data-role='edges']");
		this.$nodes = this.$root.find("[data-role='nodes']");
		this.$queue = this.$root.find("[data-role='queue-summary']");
		this.$summary = this.$root.find("[data-role='run-summary']");
		this.$providerJobs = this.$root.find("[data-role='provider-jobs']");
		this.$ledgerSummary = this.$root.find("[data-role='ledger-summary']");
		this.$runErrors = this.$root.find("[data-role='run-errors']");
		this.$runTimeline = this.$root.find("[data-role='run-timeline']");
		this.$history = this.$root.find("[data-role='history']");
		this.$assets = this.$root.find("[data-role='asset-output']");
		this.$draftWarnings = this.$root.find("[data-role='draft-warnings']");
		this.$nodeEditor = this.$root.find("[data-role='node-editor']");
		this.$edgeEditor = this.$root.find("[data-role='edge-editor']");
		this.$edgeList = this.$root.find("[data-role='edge-list']");
		this.$palette.on("click", "[data-action='add-node']", (event) => {
			const nodeType = $(event.currentTarget).attr("data-node-type");
			this.addNodeFromMetadata(nodeType);
		});
		this.$templateLibrary.on("click", "[data-action='refresh-templates']", () => {
			this.loadTemplates();
		});
		this.$templateLibrary.on("click", "[data-action='save-template']", () => {
			this.saveCurrentWorkflowAsTemplate();
		});
		this.$templateLibrary.on("click", "[data-action='load-template-preview']", (event) => {
			this.loadTemplatePreview($(event.currentTarget).attr("data-template-name"));
		});
		this.$templateLibrary.on("click", "[data-action='create-workflow-from-template']", (event) => {
			this.createWorkflowFromTemplate($(event.currentTarget).attr("data-template-name"));
		});
		this.$templatePreview.on("click", "[data-action='create-workflow-from-template']", (event) => {
			this.createWorkflowFromTemplate($(event.currentTarget).attr("data-template-name"));
		});
		this.$toolMode.on("change", "[data-tool-template]", (event) => {
			this.loadToolModeTemplate($(event.currentTarget).val());
		});
		this.$toolMode.on("click", "[data-action='refresh-tool-templates']", () => {
			this.loadTemplates();
		});
		this.$toolMode.on("click", "[data-action='run-tool-mode']", () => {
			this.runToolModeForm();
		});
		this.$nodes.on("click", "[data-node-id]", (event) => {
			this.selectNode($(event.currentTarget).attr("data-node-id"));
		});
		this.$nodeEditor.on("input change", "[data-config-field]", (event) => {
			this.updateSelectedNodeConfig(event.currentTarget);
		});
		this.$nodeEditor.on("input change", "[data-position-field]", (event) => {
			this.updateSelectedNodePosition(event.currentTarget);
		});
		this.$nodeEditor.on("click", "[data-action='delete-selected-node']", () => {
			this.deleteSelectedNode();
		});
		this.$edgeEditor.on("change", "[data-edge-source], [data-edge-target]", () => {
			this.renderEdgeEditor();
		});
		this.$edgeEditor.on("click", "[data-action='add-edge']", () => {
			this.addEdgeFromEditor();
		});
		this.$edgeList.on("click", "[data-action='delete-edge']", (event) => {
			this.deleteEdge($(event.currentTarget).attr("data-edge-id"));
		});
		this.$assets.on("click", "[data-action='copy-asset-url']", (event) => {
			this.copyAssetUrl($(event.currentTarget).attr("data-asset-name"));
		});
		this.$assets.on("click", "[data-action='refresh-asset']", (event) => {
			this.refreshAssetCard($(event.currentTarget).attr("data-asset-name"));
		});
	}

	show() {
		this.loadObjectInfo();
		this.loadTemplates();
		this.refreshQueue();
		if (this.workflowRun) {
			this.refreshRun();
		}
	}

	loadObjectInfo() {
		return frappe.call("slow_ai.api.nodes.get_object_info").then((response) => {
			this.objectInfo = response.message.nodes || {};
			this.renderPalette();
		});
	}

	loadWorkflow() {
		const workflow = this.workflowField.get_value();
		if (!workflow) {
			return Promise.resolve();
		}
		return frappe.call("slow_ai.api.workflows.get_workflow", { workflow }).then((response) => {
			const draft = response.message;
			this.workflow = draft.name;
			this.projectField.set_value(draft.project);
			this.titleField.set_value(draft.title);
			this.nodes = this.withPositions(draft.nodes || [], draft.layout || {});
			this.edges = draft.edges || [];
			this.layout = draft.layout || {};
			this.selectedNodeId = this.nodes.length ? this.nodes[0].id : null;
			this.workflowRun = null;
			this.nodeRunsByNodeId = {};
			this.setStatus(__("Loaded {0}", [draft.name]));
			this.render();
			this.clearRunMonitor();
			this.renderAssetOutputs([]);
		});
	}

	saveWorkflow() {
		const project = this.projectField.get_value();
		if (!project) {
			frappe.msgprint(__("Select an AI Project before saving."));
			return Promise.resolve();
		}
		const title = this.titleField.get_value() || __("Untitled AI Workflow");
		this.captureLayout();
		return frappe.call("slow_ai.api.workflows.save_workflow", {
			project,
			title,
			workflow: this.workflow || this.workflowField.get_value() || null,
			nodes: this.nodes,
			edges: this.edges,
			layout: this.layout,
		}).then((response) => {
			const draft = response.message;
			this.workflow = draft.name;
			this.workflowField.set_value(draft.name);
			this.setStatus(__("Saved {0}", [draft.name]));
			this.render();
		});
	}

	startRun() {
		const workflow = this.workflow || this.workflowField.get_value();
		if (!workflow) {
			frappe.msgprint(__("Save or load a workflow before starting a run."));
			return Promise.resolve();
		}
		return this.confirmProviderRun().then((confirmed) => {
			if (!confirmed) {
				this.setStatus(__("Run cancelled"));
				return null;
			}
			return frappe.call("slow_ai.api.runs.start_run", { workflow }).then((response) => {
				const result = response.message;
				this.workflowRun = result.workflow_run;
				this.setStatus(__("Queued {0}", [result.workflow_run]));
				this.startPolling();
				this.refreshRun();
				this.refreshQueue();
			});
		});
	}

	confirmProviderRun() {
		const providerNodes = this.providerNodes();
		if (!providerNodes.length) {
			return Promise.resolve(true);
		}
		return this.loadModelMetadata(providerNodes).then((modelMetadata) => {
			const message = this.providerConfirmationMessage(providerNodes, modelMetadata);
			return new Promise((resolve) => {
				frappe.confirm(message, () => resolve(true), () => resolve(false));
			});
		});
	}

	providerNodes() {
		return this.nodes.filter((node) => node.type && node.type.indexOf("provider_") === 0);
	}

	loadModelMetadata(providerNodes) {
		const modelIds = providerNodes
			.map((node) => node.config && node.config.model)
			.filter((model) => model !== undefined && model !== null && model !== "");
		if (!modelIds.length) {
			return Promise.resolve({});
		}
		return frappe
			.call("slow_ai.api.models.get_model_metadata", { model_ids: modelIds })
			.then((response) => (response.message && response.message.models) || {});
	}

	providerConfirmationMessage(providerNodes, modelMetadata) {
		const rows = providerNodes
			.map((node) => {
				const config = node.config || {};
				const provider = config.provider || __("Unknown provider");
				const model = config.model || __("Unknown model");
				const metadata = modelMetadata[model] || {};
				const cost = metadata.pricing_known
					? `${metadata.currency || "USD"} ${metadata.estimated_cost_usd} / ${metadata.pricing_unit || "run"}`
					: __("cost unknown");
				return `<li><strong>${this.escape(node.label || node.id)}</strong>: ${this.escape(provider)} / ${this.escape(model)} · ${this.escape(cost)}</li>`;
			})
			.join("");
		return `<p>${__("This workflow may call an external provider and spend credits.")}</p>
			<ul>${rows}</ul>
			<p>${__("Review provider and model settings before continuing.")}</p>`;
	}

	refreshRun() {
		if (!this.workflowRun) {
			this.$summary.html(`<div class="slow-ai-canvas__empty">${__("No run selected")}</div>`);
			this.clearHistoryPanels();
			return Promise.resolve();
		}
		return frappe.call("slow_ai.api.runs.get_run_status", { workflow_run: this.workflowRun }).then((response) => {
			const status = response.message;
			this.nodeRunsByNodeId = {};
			(status.node_runs || []).forEach((nodeRun) => {
				this.nodeRunsByNodeId[nodeRun.node_id] = nodeRun;
			});
			this.$run.text(`${status.workflow_run} · ${status.status}`);
			this.renderRunSummary(status);
			this.render();
			if (this.isTerminalStatus(status.status)) {
				this.stopPolling();
			} else {
				this.startPolling();
			}
			return this.refreshHistory();
		});
	}

	refreshHistory() {
		if (!this.workflowRun) {
			return Promise.resolve();
		}
		return frappe.call("slow_ai.api.runs.get_history", { workflow_run: this.workflowRun }).then((response) => {
			this.renderHistory(response.message);
		});
	}

	refreshQueue() {
		return frappe.call("slow_ai.api.queue.get_queue_status").then((response) => {
			const counts = response.message.counts || {};
			this.$queue.html(`
				<div class="slow-ai-canvas__metric">${__("Queued")}: ${counts.queued || 0}</div>
				<div class="slow-ai-canvas__metric">${__("Running")}: ${counts.running || 0}</div>
			`);
		});
	}

	loadTemplates() {
		if (!this.$templateLibrary) {
			return Promise.resolve();
		}
		this.$templateLibrary.html(`<div class="slow-ai-canvas__empty">${__("Loading templates")}</div>`);
		return frappe.call("slow_ai.api.templates.list_templates").then((response) => {
			this.templates = (response.message && response.message.templates) || [];
			this.renderTemplateLibrary();
			this.renderToolModePanel();
		});
	}

	renderTemplateLibrary() {
		if (!this.$templateLibrary) {
			return;
		}
		const actions = `<div class="slow-ai-canvas__template-actions">
			<button class="btn btn-xs btn-default" type="button" data-action="refresh-templates">${__("Refresh Templates")}</button>
			<button class="btn btn-xs btn-default" type="button" data-action="save-template">${__("Save Current Workflow as Template")}</button>
		</div>`;
		if (!this.templates.length) {
			this.$templateLibrary.html(`${actions}<div class="slow-ai-canvas__empty">${__("No templates")}</div>`);
			return;
		}
		const rows = this.templates.map((template) => this.renderTemplateCard(template)).join("");
		this.$templateLibrary.html(`${actions}${rows}`);
	}

	renderTemplateCard(template) {
		const preview = template.preview_asset
			? `<div class="slow-ai-canvas__template-meta">${__("Preview Asset")}: ${this.escape(template.preview_asset)}</div>`
			: "";
		return `<div class="slow-ai-canvas__template-card" data-template-name="${this.escape(template.name)}">
			<div class="slow-ai-canvas__template-title">${this.escape(template.template_name || template.name)}</div>
			<div class="slow-ai-canvas__template-meta">${this.escape(template.category || __("Uncategorized"))} · ${this.escape(template.status || "")}</div>
			${template.description ? `<div class="slow-ai-canvas__template-description">${this.escape(template.description)}</div>` : ""}
			${preview}
			<div class="slow-ai-canvas__template-card-actions">
				<button class="btn btn-xs btn-default" type="button" data-action="load-template-preview" data-template-name="${this.escape(template.name)}">${__("Load Template Preview")}</button>
				<button class="btn btn-xs btn-primary" type="button" data-action="create-workflow-from-template" data-template-name="${this.escape(template.name)}">${__("Create Workflow")}</button>
			</div>
		</div>`;
	}

	saveCurrentWorkflowAsTemplate() {
		const defaultName = `${this.titleField.get_value() || __("Untitled AI Workflow")} Template`;
		const fields = [
			{ label: __("Template Name"), fieldname: "template_name", fieldtype: "Data", reqd: 1, default: defaultName },
			{ label: __("Category"), fieldname: "category", fieldtype: "Data", default: "Canvas" },
			{ label: __("Description"), fieldname: "description", fieldtype: "Small Text" },
			{
				label: __("Status"),
				fieldname: "status",
				fieldtype: "Select",
				options: "DRAFT\nPUBLISHED\nARCHIVED",
				default: "DRAFT",
			},
		];
		return new Promise((resolve) => {
			frappe.prompt(
				fields,
				(values) => {
					this.captureLayout();
					frappe
						.call("slow_ai.api.templates.save_template", {
							template_name: values.template_name,
							status: values.status || "DRAFT",
							category: values.category || "",
							description: values.description || "",
							nodes: this.nodes,
							edges: this.edges,
							layout: this.layout,
						})
						.then((response) => {
							this.selectedTemplate = response.message;
							this.setStatus(__("Saved template {0}", [response.message.name]));
							this.renderTemplatePreview();
							this.loadTemplates().then(resolve);
						});
				},
				__("Save Template"),
				__("Save")
			);
		});
	}

	loadTemplatePreview(templateName) {
		if (!templateName) {
			return Promise.resolve();
		}
		this.$templatePreview.html(`<div class="slow-ai-canvas__empty">${__("Loading template preview")}</div>`);
		return frappe.call("slow_ai.api.templates.get_template", { template: templateName }).then((response) => {
			this.selectedTemplate = response.message;
			this.renderTemplatePreview();
			this.setStatus(__("Loaded template preview {0}", [this.selectedTemplate.name]));
		});
	}

	renderTemplatePreview() {
		if (!this.$templatePreview) {
			return;
		}
		const template = this.selectedTemplate;
		if (!template) {
			this.$templatePreview.html(`<div class="slow-ai-canvas__empty">${__("No template preview selected")}</div>`);
			return;
		}
		const nodes = template.nodes || [];
		const edges = template.edges || [];
		const nodeRows = nodes
			.map((node) => `<div class="slow-ai-canvas__template-preview-row">${this.escape(node.label || node.id)} · ${this.escape(node.type)}</div>`)
			.join("");
		this.$templatePreview.html(`<div class="slow-ai-canvas__template-preview-card">
			<div class="slow-ai-canvas__template-title">${this.escape(template.template_name || template.name)}</div>
			<div class="slow-ai-canvas__template-meta">${this.escape(template.category || __("Uncategorized"))} · ${this.escape(template.status || "")}</div>
			${template.description ? `<div class="slow-ai-canvas__template-description">${this.escape(template.description)}</div>` : ""}
			<div class="slow-ai-canvas__template-preview-row">${__("Nodes")}: ${nodes.length}</div>
			<div class="slow-ai-canvas__template-preview-row">${__("Edges")}: ${edges.length}</div>
			${template.preview_asset ? `<div class="slow-ai-canvas__template-preview-row">${__("Preview Asset")}: ${this.escape(template.preview_asset)}</div>` : ""}
			${nodeRows}
			<div class="slow-ai-canvas__template-card-actions">
				<button class="btn btn-xs btn-primary" type="button" data-action="create-workflow-from-template" data-template-name="${this.escape(template.name)}">${__("Create Workflow from Template")}</button>
			</div>
		</div>`);
	}

	createWorkflowFromTemplate(templateName) {
		const template = templateName || (this.selectedTemplate && this.selectedTemplate.name);
		const project = this.projectField.get_value();
		if (!template) {
			frappe.msgprint(__("Select a template before creating a workflow."));
			return Promise.resolve();
		}
		if (!project) {
			frappe.msgprint(__("Select an AI Project before creating a workflow from a template."));
			return Promise.resolve();
		}
		const title =
			(this.selectedTemplate && this.selectedTemplate.name === template && this.selectedTemplate.template_name) ||
			this.titleField.get_value() ||
			__("Untitled AI Workflow");
		return frappe
			.call("slow_ai.api.templates.create_workflow_from_template", {
				template,
				project,
				title,
			})
			.then((response) => {
				const draft = response.message;
				this.workflow = draft.name;
				this.workflowRun = null;
				this.workflowField.set_value(draft.name);
				this.titleField.set_value(draft.title);
				this.nodes = this.withPositions(draft.nodes || [], draft.layout || {});
				this.edges = draft.edges || [];
				this.layout = draft.layout || {};
				this.selectedNodeId = this.nodes.length ? this.nodes[0].id : null;
				this.nodeRunsByNodeId = {};
				this.setStatus(__("Created workflow {0} from template", [draft.name]));
				this.clearRunMonitor();
				this.renderAssetOutputs([]);
				this.render();
			});
	}

	renderToolModePanel() {
		if (!this.$toolMode) {
			return;
		}
		const options = this.templates
			.map((template) => {
				const selected = this.toolModeTemplate && this.toolModeTemplate.name === template.name ? "selected" : "";
				return `<option value="${this.escape(template.name)}" ${selected}>${this.escape(template.template_name || template.name)}</option>`;
			})
			.join("");
		const selector = `<label class="slow-ai-canvas__tool-field">
			<span>${__("Template")}</span>
			<select class="form-control input-xs" data-tool-template>
				<option value="">${__("Select a template")}</option>
				${options}
			</select>
		</label>`;
		const actions = `<div class="slow-ai-canvas__tool-actions">
			<button class="btn btn-xs btn-default" type="button" data-action="refresh-tool-templates">${__("Refresh Templates")}</button>
		</div>`;
		if (!this.templates.length) {
			this.$toolMode.html(`${actions}<div class="slow-ai-canvas__empty">${__("No templates available")}</div>`);
			return;
		}
		if (!this.toolModeTemplate) {
			this.$toolMode.html(`${selector}${actions}<div class="slow-ai-canvas__empty">${__("Select a template to run as a tool")}</div>`);
			return;
		}
		this.$toolMode.html(`${selector}${this.renderToolModeForm(this.toolModeTemplate)}`);
	}

	loadToolModeTemplate(templateName) {
		if (!templateName) {
			this.toolModeTemplate = null;
			this.renderToolModePanel();
			return Promise.resolve();
		}
		this.$toolMode.html(`<div class="slow-ai-canvas__empty">${__("Loading tool form")}</div>`);
		return frappe.call("slow_ai.api.templates.get_template", { template: templateName }).then((response) => {
			this.toolModeTemplate = response.message;
			this.renderToolModePanel();
			this.setStatus(__("Loaded tool form {0}", [this.toolModeTemplate.template_name || this.toolModeTemplate.name]));
		});
	}

	renderToolModeForm(template) {
		const nodes = template.nodes || [];
		const formRows = nodes.map((node) => this.renderToolModeNodeControl(node)).filter(Boolean).join("");
		const providerRows = nodes
			.filter((node) => node.type && node.type.indexOf("provider_") === 0)
			.map((node) => this.renderToolModeProviderSummary(node))
			.join("");
		return `<div class="slow-ai-canvas__tool-card" data-tool-template-name="${this.escape(template.name)}">
			<div class="slow-ai-canvas__tool-title">${this.escape(template.template_name || template.name)}</div>
			<div class="slow-ai-canvas__tool-meta">${this.escape(template.category || __("Uncategorized"))} · ${this.escape(template.status || "")}</div>
			${template.description ? `<div class="slow-ai-canvas__template-description">${this.escape(template.description)}</div>` : ""}
			${formRows || `<div class="slow-ai-canvas__empty">${__("No editable form fields")}</div>`}
			${providerRows}
			<div class="slow-ai-canvas__tool-actions">
				<button class="btn btn-xs btn-primary" type="button" data-action="run-tool-mode">${__("Run Tool")}</button>
			</div>
		</div>`;
	}

	renderToolModeNodeControl(node) {
		const config = node.config || {};
		const label = node.label || node.id;
		if (node.type === "text_prompt") {
			return `<label class="slow-ai-canvas__tool-field">
				<span>${this.escape(label)}</span>
				<textarea class="form-control input-xs slow-ai-canvas__tool-textarea" data-tool-node-id="${this.escape(node.id)}" data-tool-config-field="text">${this.escape(config.text || "")}</textarea>
			</label>`;
		}
		if (node.type === "upload_asset") {
			return `<div class="slow-ai-canvas__tool-section">
				<div class="slow-ai-canvas__tool-title">${this.escape(label)}</div>
				<label class="slow-ai-canvas__tool-field">
					<span>${__("Asset")}</span>
					<input class="form-control input-xs" type="text" placeholder="${__("AI Asset name")}" data-tool-node-id="${this.escape(node.id)}" data-tool-config-field="asset" value="${this.escape(config.asset || "")}">
				</label>
				<label class="slow-ai-canvas__tool-field">
					<span>${__("Asset Type")}</span>
					<select class="form-control input-xs" data-tool-node-id="${this.escape(node.id)}" data-tool-config-field="asset_type">
						${this.renderAssetTypeOption("IMAGE", config.asset_type)}
						${this.renderAssetTypeOption("VIDEO", config.asset_type)}
						${this.renderAssetTypeOption("AUDIO", config.asset_type)}
						${this.renderAssetTypeOption("MASK", config.asset_type)}
					</select>
				</label>
				<div class="slow-ai-canvas__tool-meta">${__("Upload assets through AI Asset for now, then paste the asset name here.")}</div>
			</div>`;
		}
		return "";
	}

	renderAssetTypeOption(assetType, selectedAssetType) {
		const selected = String(assetType) === String(selectedAssetType || "") ? "selected" : "";
		return `<option value="${this.escape(assetType)}" ${selected}>${this.escape(assetType)}</option>`;
	}

	renderToolModeProviderSummary(node) {
		const config = node.config || {};
		const parameters = this.formatJsonValue(config.parameters || {});
		return `<div class="slow-ai-canvas__tool-section">
			<div class="slow-ai-canvas__tool-title">${this.escape(node.label || node.id)}</div>
			<div class="slow-ai-canvas__tool-readonly"><span>${__("Provider")}</span>: ${this.escape(config.provider || "")}</div>
			<div class="slow-ai-canvas__tool-readonly"><span>${__("Model")}</span>: ${this.escape(config.model || "")}</div>
			${config.provider_account ? `<div class="slow-ai-canvas__tool-readonly"><span>${__("Provider Account")}</span>: ${this.escape(config.provider_account)}</div>` : ""}
			<div class="slow-ai-canvas__tool-readonly"><span>${__("Parameters")}</span>: ${this.escape(parameters || "{}")}</div>
		</div>`;
	}

	runToolModeForm() {
		const project = this.projectField.get_value();
		const template = this.toolModeTemplate;
		if (!project) {
			frappe.msgprint(__("Select an AI Project before running Tool Mode."));
			return Promise.resolve();
		}
		if (!template) {
			frappe.msgprint(__("Select a template before running Tool Mode."));
			return Promise.resolve();
		}
		const title = `${template.template_name || template.name} Run`;
		const formValues = this.collectToolModeValues();
		return frappe
			.call("slow_ai.api.templates.create_workflow_from_template", {
				template: template.name,
				project,
				title,
			})
			.then((response) => {
				const draft = response.message;
				this.workflow = draft.name;
				this.workflowRun = null;
				this.workflowField.set_value(draft.name);
				this.titleField.set_value(draft.title);
				this.nodes = this.applyToolModeValues(this.withPositions(draft.nodes || [], draft.layout || {}), formValues);
				this.edges = draft.edges || [];
				this.layout = draft.layout || {};
				this.selectedNodeId = this.nodes.length ? this.nodes[0].id : null;
				this.nodeRunsByNodeId = {};
				this.clearRunMonitor();
				this.renderAssetOutputs([]);
				this.render();
				return this.saveWorkflow();
			})
			.then(() => this.startRun());
	}

	collectToolModeValues() {
		const values = {};
		this.$toolMode.find("[data-tool-node-id][data-tool-config-field]").each((index, element) => {
			const nodeId = $(element).attr("data-tool-node-id");
			const fieldname = $(element).attr("data-tool-config-field");
			values[nodeId] = values[nodeId] || {};
			values[nodeId][fieldname] = $(element).val();
		});
		return values;
	}

	applyToolModeValues(nodes, values) {
		return nodes.map((node) => {
			const nodeValues = values[node.id];
			if (!nodeValues) {
				return node;
			}
			return {
				...node,
				config: {
					...(node.config || {}),
					...nodeValues,
				},
			};
		});
	}

	startPolling() {
		if (this.pollTimer || !this.workflowRun) {
			return;
		}
		this.pollTimer = window.setInterval(() => {
			this.refreshRun();
			this.refreshQueue();
		}, 5000);
	}

	stopPolling() {
		if (!this.pollTimer) {
			return;
		}
		window.clearInterval(this.pollTimer);
		this.pollTimer = null;
	}

	isTerminalStatus(status) {
		return ["SUCCEEDED", "FAILED", "CANCELLED", "EXPIRED"].includes(status);
	}

	bindRealtime() {
		if (!frappe.realtime) {
			return;
		}
		["slow_ai_workflow_run_update", "slow_ai_node_run_update", "slow_ai_provider_job_update"].forEach((eventName) => {
			frappe.realtime.on(eventName, (payload) => {
				if (payload && payload.workflow_run && payload.workflow_run !== this.workflowRun) {
					return;
				}
				this.refreshRun();
				this.refreshQueue();
			});
		});
	}

	newDefaultDraft() {
		this.workflow = null;
		this.workflowRun = null;
		this.stopPolling();
		this.workflowField.set_value("");
		this.titleField.set_value("Untitled AI Workflow");
		this.nodes = this.defaultNodes();
		this.edges = this.defaultEdges();
		this.selectedNodeId = null;
		this.layout = { nodes: this.nodes.map((node) => ({ id: node.id, ...node.position })) };
		this.nodeRunsByNodeId = {};
		this.setStatus(__("New draft"));
		this.clearRunMonitor();
		this.renderAssetOutputs([]);
		this.render();
	}

	defaultNodes() {
		return [
			{
				id: "prompt_1",
				type: "text_prompt",
				label: "Prompt",
				position: { x: 96, y: 128 },
				config: { text: "A concise product prompt" },
			},
			{
				id: "image_1",
				type: "provider_text_to_image",
				label: "Provider Text to Image",
				position: { x: 376, y: 128 },
				config: {
					provider: "wavespeed",
					model: "wavespeed-ai/flux-dev",
					parameters: {
						size: "1024*1024",
						num_images: 1,
						enable_base64_output: false,
					},
				},
			},
			{
				id: "output_1",
				type: "export_output",
				label: "Output",
				position: { x: 656, y: 128 },
				config: {},
			},
		];
	}

	defaultEdges() {
		return [
			{
				id: "edge_1",
				source: "prompt_1",
				source_port: "text",
				target: "image_1",
				target_port: "prompt",
			},
			{
				id: "edge_2",
				source: "image_1",
				source_port: "image",
				target: "output_1",
				target_port: "image",
			},
		];
	}

	withPositions(nodes, layout) {
		const positions = {};
		((layout && layout.nodes) || []).forEach((row) => {
			positions[row.id] = { x: row.x || 0, y: row.y || 0 };
		});
		return nodes.map((node, index) => ({
			...node,
			position: node.position || positions[node.id] || { x: 96 + index * 280, y: 128 },
		}));
	}

	captureLayout() {
		this.layout = {
			nodes: this.nodes.map((node) => ({
				id: node.id,
				x: node.position ? node.position.x : 0,
				y: node.position ? node.position.y : 0,
			})),
		};
	}

	render() {
		this.renderPalette();
		this.renderNodes();
		this.renderEdges();
		this.renderNodeEditor();
		this.renderEdgeEditor();
		this.renderEdgeList();
		this.renderDraftWarnings();
	}

	renderPalette() {
		if (!this.$palette || !Object.keys(this.objectInfo).length) {
			return;
		}
		const categories = this.paletteCategories();
		this.$palette.html(categories.map((category) => this.renderPaletteCategory(category)).join(""));
	}

	paletteCategories() {
		const order = ["input", "provider", "image", "video", "audio", "utility", "output"];
		const categories = {};
		order.forEach((category) => {
			categories[category] = [];
		});
		Object.values(this.objectInfo).forEach((node) => {
			const category = this.paletteCategoryForNode(node);
			categories[category].push(node);
		});
		return order.map((category) => ({
			name: category,
			nodes: categories[category].sort((a, b) => (a.label || a.type).localeCompare(b.label || b.type)),
		}));
	}

	paletteCategoryForNode(node) {
		const category = (node.category || "").toLowerCase();
		if (["input", "provider", "image", "video", "audio", "output"].includes(category)) {
			return category;
		}
		return "utility";
	}

	renderPaletteCategory(category) {
		const nodeList = category.nodes.length
			? category.nodes.map((node) => this.renderPaletteNode(node)).join("")
			: `<div class="slow-ai-canvas__empty">${__("No registered nodes")}</div>`;
		return `<section class="slow-ai-canvas__palette-category" data-node-category="${this.escape(category.name)}">
			<div class="slow-ai-canvas__category-title">${this.escape(this.titleCase(category.name))}</div>
			${nodeList}
		</section>`;
	}

	renderPaletteNode(node) {
		return `<div class="slow-ai-canvas__node-item" data-palette-node-type="${this.escape(node.type)}">
			<div class="slow-ai-canvas__node-title">${this.escape(node.label || node.type)}</div>
			<div class="slow-ai-canvas__node-meta">${this.escape(node.type)}</div>
			<div class="slow-ai-canvas__node-meta">${__("Category")}: ${this.escape(node.category || "utility")}</div>
			${this.renderSchemaSummary(__("Inputs"), node.input_schema)}
			${this.renderSchemaSummary(__("Config"), node.config_schema)}
			${this.renderSchemaSummary(__("Outputs"), node.output_schema)}
			<button class="btn btn-xs btn-default slow-ai-canvas__add-node" type="button" data-action="add-node" data-node-type="${this.escape(node.type)}">${__("Add Node")}</button>
		</div>`;
	}

	renderSchemaSummary(label, schema) {
		const summary = this.schemaSummary(schema);
		return `<div class="slow-ai-canvas__schema-row"><span>${this.escape(label)}:</span> ${this.escape(summary)}</div>`;
	}

	schemaSummary(schema) {
		const entries = Object.entries(schema || {});
		if (!entries.length) {
			return __("none");
		}
		return entries
			.map(([fieldname, spec]) => {
				const required = spec && spec.required ? "*" : "";
				const type = spec && spec.type ? spec.type : "JSON";
				return `${fieldname}:${type}${required}`;
			})
			.join(", ");
	}

	addNodeFromMetadata(nodeType) {
		const metadata = this.objectInfo[nodeType];
		if (!metadata) {
			return;
		}
		const index = this.nodes.length + 1;
		const node = {
			id: this.nextNodeId(nodeType),
			type: metadata.type,
			label: metadata.label || metadata.type,
			position: { x: 96 + ((index - 1) % 3) * 280, y: 128 + Math.floor((index - 1) / 3) * 150 },
			config: this.defaultConfigFromSchema(metadata.config_schema || {}),
		};
		this.nodes.push(node);
		this.selectedNodeId = node.id;
		this.captureLayout();
		this.setStatus(__("Added {0}", [metadata.label || metadata.type]));
		this.render();
	}

	nextNodeId(nodeType) {
		const base = String(nodeType || "node").replace(/[^a-zA-Z0-9_]/g, "_");
		let index = this.nodes.length + 1;
		let candidate = `${base}_${index}`;
		const existing = new Set(this.nodes.map((node) => node.id));
		while (existing.has(candidate)) {
			index += 1;
			candidate = `${base}_${index}`;
		}
		return candidate;
	}

	defaultConfigFromSchema(schema) {
		const config = {};
		Object.entries(schema || {}).forEach(([fieldname, spec]) => {
			if (!spec || !Object.prototype.hasOwnProperty.call(spec, "default")) {
				return;
			}
			config[fieldname] = spec.default;
		});
		return config;
	}

	titleCase(value) {
		return String(value || "").replace(/\b\w/g, (char) => char.toUpperCase());
	}

	findNode(nodeId) {
		return this.nodes.find((node) => node.id === nodeId) || null;
	}

	nodeMetadata(node) {
		return node && this.objectInfo ? this.objectInfo[node.type] || null : null;
	}

	portEntries(node, schemaName) {
		const metadata = this.nodeMetadata(node);
		return Object.entries((metadata && metadata[schemaName]) || {});
	}

	inputPorts(node) {
		return this.portEntries(node, "input_schema");
	}

	outputPorts(node) {
		return this.portEntries(node, "output_schema");
	}

	portType(node, schemaName, portName) {
		const metadata = this.nodeMetadata(node);
		const schema = (metadata && metadata[schemaName]) || {};
		const spec = schema[portName] || {};
		return spec.type || "JSON";
	}

	portsCompatible(sourceNode, sourcePort, targetNode, targetPort) {
		if (!sourceNode || !targetNode || !sourcePort || !targetPort) {
			return false;
		}
		return (
			this.portType(sourceNode, "output_schema", sourcePort) ===
			this.portType(targetNode, "input_schema", targetPort)
		);
	}

	selectNode(nodeId) {
		this.selectedNodeId = nodeId;
		this.render();
	}

	deleteSelectedNode() {
		if (!this.selectedNodeId) {
			return;
		}
		const nodeId = this.selectedNodeId;
		this.nodes = this.nodes.filter((node) => node.id !== nodeId);
		this.edges = this.edges.filter((edge) => edge.source !== nodeId && edge.target !== nodeId);
		this.selectedNodeId = this.nodes.length ? this.nodes[0].id : null;
		this.captureLayout();
		this.setStatus(__("Deleted node {0}", [nodeId]));
		this.render();
	}

	updateSelectedNodePosition(input) {
		const node = this.findNode(this.selectedNodeId);
		if (!node) {
			return;
		}
		const fieldname = $(input).attr("data-position-field");
		const value = Number(input.value);
		node.position = node.position || { x: 0, y: 0 };
		node.position[fieldname] = Number.isFinite(value) ? value : 0;
		this.captureLayout();
		this.renderNodes();
		this.renderEdges();
		this.renderDraftWarnings();
	}

	updateSelectedNodeConfig(input) {
		const node = this.findNode(this.selectedNodeId);
		if (!node) {
			return;
		}
		const fieldname = $(input).attr("data-config-field");
		const metadata = this.nodeMetadata(node) || {};
		const spec = (metadata.config_schema || {})[fieldname] || {};
		node.config = node.config || {};
		node.config[fieldname] = this.valueFromControl(input, spec);
		this.renderDraftWarnings();
	}

	valueFromControl(input, spec) {
		const valueType = spec.value_type || spec.type || "string";
		if (input.type === "checkbox") {
			return Boolean(input.checked);
		}
		if (["number", "integer", "float"].includes(valueType)) {
			const value = Number(input.value);
			return Number.isFinite(value) ? value : null;
		}
		if (valueType === "object" || valueType === "array" || spec.type === "JSON") {
			if (!input.value) {
				return valueType === "array" ? [] : {};
			}
			try {
				return JSON.parse(input.value);
			} catch (error) {
				return input.value;
			}
		}
		return input.value;
	}

	nextEdgeId() {
		let index = this.edges.length + 1;
		let candidate = `edge_${index}`;
		const existing = new Set(this.edges.map((edge) => edge.id));
		while (existing.has(candidate)) {
			index += 1;
			candidate = `edge_${index}`;
		}
		return candidate;
	}

	addEdgeFromEditor() {
		const source = this.$edgeEditor.find("[data-edge-source]").val();
		const sourcePort = this.$edgeEditor.find("[data-edge-source-port]").val();
		const target = this.$edgeEditor.find("[data-edge-target]").val();
		const targetPort = this.$edgeEditor.find("[data-edge-target-port]").val();
		const sourceNode = this.findNode(source);
		const targetNode = this.findNode(target);
		if (!this.portsCompatible(sourceNode, sourcePort, targetNode, targetPort)) {
			this.setStatus(__("Ports are not compatible"));
			return;
		}
		const duplicate = this.edges.some(
			(edge) =>
				edge.source === source &&
				edge.source_port === sourcePort &&
				edge.target === target &&
				edge.target_port === targetPort
		);
		if (duplicate) {
			this.setStatus(__("Edge already exists"));
			return;
		}
		this.edges.push({
			id: this.nextEdgeId(),
			source,
			source_port: sourcePort,
			target,
			target_port: targetPort,
		});
		this.setStatus(__("Added edge"));
		this.render();
	}

	deleteEdge(edgeId) {
		this.edges = this.edges.filter((edge) => edge.id !== edgeId);
		this.setStatus(__("Deleted edge {0}", [edgeId]));
		this.render();
	}

	renderNodes() {
		const html = this.nodes
			.map((node) => {
				const nodeRun = this.nodeRunsByNodeId[node.id] || {};
				const status = nodeRun.status || "DRAFT";
				const position = node.position || { x: 0, y: 0 };
				const selected = this.selectedNodeId === node.id ? "1" : "0";
				return `<div class="slow-ai-canvas__node" data-node-id="${this.escape(node.id)}" data-node-status="${this.escape(status)}" data-selected="${selected}" style="left: ${position.x}px; top: ${position.y}px;">
					<div class="slow-ai-canvas__node-name">${this.escape(node.label || node.id)}</div>
					<div class="slow-ai-canvas__node-type">${this.escape(node.type)}</div>
					<div class="slow-ai-canvas__node-status">${this.escape(status)}</div>
				</div>`;
			})
			.join("");
		this.$nodes.html(html);
	}

	renderEdges() {
		const nodeById = {};
		this.nodes.forEach((node) => {
			nodeById[node.id] = node;
		});
		const lines = this.edges
			.map((edge) => {
				const source = nodeById[edge.source];
				const target = nodeById[edge.target];
				if (!source || !target) {
					return "";
				}
				const sx = (source.position ? source.position.x : 0) + 188;
				const sy = (source.position ? source.position.y : 0) + 44;
				const tx = target.position ? target.position.x : 0;
				const ty = (target.position ? target.position.y : 0) + 44;
				const mid = Math.max(40, (tx - sx) / 2);
				return `<path class="slow-ai-canvas__edge" d="M ${sx} ${sy} C ${sx + mid} ${sy}, ${tx - mid} ${ty}, ${tx} ${ty}"></path>`;
			})
			.join("");
		this.$edges.html(lines);
	}

	renderNodeEditor() {
		if (!this.$nodeEditor) {
			return;
		}
		const node = this.findNode(this.selectedNodeId);
		if (!node) {
			this.$nodeEditor.html(`<div class="slow-ai-canvas__empty">${__("Select a node")}</div>`);
			return;
		}
		const metadata = this.nodeMetadata(node);
		const configRows = Object.entries((metadata && metadata.config_schema) || {});
		const configControls = configRows.length
			? configRows.map(([fieldname, spec]) => this.renderConfigControl(node, fieldname, spec)).join("")
			: `<div class="slow-ai-canvas__empty">${__("No config fields")}</div>`;
		const position = node.position || { x: 0, y: 0 };
		this.$nodeEditor.html(`
			<div class="slow-ai-canvas__editor-title">${this.escape(node.label || node.id)}</div>
			<div class="slow-ai-canvas__editor-meta">${this.escape(node.id)} · ${this.escape(node.type)}</div>
			<div class="slow-ai-canvas__field-grid">
				<label class="slow-ai-canvas__field">
					<span>${__("X")}</span>
					<input class="form-control input-xs" type="number" data-position-field="x" value="${this.escape(position.x)}">
				</label>
				<label class="slow-ai-canvas__field">
					<span>${__("Y")}</span>
					<input class="form-control input-xs" type="number" data-position-field="y" value="${this.escape(position.y)}">
				</label>
			</div>
			<div class="slow-ai-canvas__editor-subhead">${__("Config")}</div>
			${configControls}
			<button class="btn btn-xs btn-danger slow-ai-canvas__delete-node" type="button" data-action="delete-selected-node">${__("Delete Node")}</button>
		`);
	}

	renderConfigControl(node, fieldname, spec) {
		const value = node.config && Object.prototype.hasOwnProperty.call(node.config, fieldname) ? node.config[fieldname] : "";
		const label = spec.label || fieldname;
		const required = spec.required ? " *" : "";
		const typeSummary = spec.type || spec.value_type || "TEXT";
		const common = `data-config-field="${this.escape(fieldname)}"`;
		let control = "";
		if (Array.isArray(spec.options) && spec.options.length) {
			const options = spec.options
				.map((option) => {
					const selected = String(option) === String(value) ? "selected" : "";
					return `<option value="${this.escape(option)}" ${selected}>${this.escape(option)}</option>`;
				})
				.join("");
			control = `<select class="form-control input-xs" ${common}>${options}</select>`;
		} else if (spec.value_type === "boolean") {
			const checked = value ? "checked" : "";
			control = `<input type="checkbox" ${common} ${checked}>`;
		} else if (spec.value_type === "object" || spec.value_type === "array" || spec.type === "JSON") {
			control = `<textarea class="form-control input-xs slow-ai-canvas__json-field" ${common}>${this.escape(this.formatJsonValue(value))}</textarea>`;
		} else if (["number", "integer", "float"].includes(spec.value_type)) {
			control = `<input class="form-control input-xs" type="number" ${common} value="${this.escape(value)}">`;
		} else {
			control = `<input class="form-control input-xs" type="text" ${common} value="${this.escape(value)}">`;
		}
		return `<label class="slow-ai-canvas__field">
			<span>${this.escape(label)}${required}</span>
			${control}
			<small>${this.escape(typeSummary)}</small>
		</label>`;
	}

	formatJsonValue(value) {
		if (value === "" || value === null || value === undefined) {
			return "";
		}
		if (typeof value === "string") {
			return value;
		}
		return JSON.stringify(value, null, 2);
	}

	renderEdgeEditor() {
		if (!this.$edgeEditor) {
			return;
		}
		const sourceNode = this.findNode(this.$edgeEditor.find("[data-edge-source]").val()) || this.firstNodeWithPorts("output");
		const targetNode = this.findNode(this.$edgeEditor.find("[data-edge-target]").val()) || this.firstNodeWithPorts("input");
		const sourcePorts = this.outputPorts(sourceNode);
		const targetPorts = this.inputPorts(targetNode);
		this.$edgeEditor.html(`
			<div class="slow-ai-canvas__editor-subhead">${__("Add Edge")}</div>
			<label class="slow-ai-canvas__field">
				<span>${__("Source")}</span>
				${this.renderNodeSelect("data-edge-source", sourceNode && sourceNode.id, "output")}
			</label>
			<label class="slow-ai-canvas__field">
				<span>${__("Output Port")}</span>
				${this.renderPortSelect("data-edge-source-port", sourcePorts)}
			</label>
			<label class="slow-ai-canvas__field">
				<span>${__("Target")}</span>
				${this.renderNodeSelect("data-edge-target", targetNode && targetNode.id, "input")}
			</label>
			<label class="slow-ai-canvas__field">
				<span>${__("Input Port")}</span>
				${this.renderPortSelect("data-edge-target-port", targetPorts)}
			</label>
			<button class="btn btn-xs btn-default" type="button" data-action="add-edge">${__("Add Edge")}</button>
		`);
	}

	firstNodeWithPorts(direction) {
		return (
			this.nodes.find((node) =>
				direction === "output" ? this.outputPorts(node).length : this.inputPorts(node).length
			) || null
		);
	}

	renderNodeSelect(attribute, selectedNodeId, direction) {
		const rows = this.nodes
			.filter((node) => (direction === "output" ? this.outputPorts(node).length : this.inputPorts(node).length))
			.map((node) => {
				const selected = node.id === selectedNodeId ? "selected" : "";
				return `<option value="${this.escape(node.id)}" ${selected}>${this.escape(node.label || node.id)}</option>`;
			})
			.join("");
		return `<select class="form-control input-xs" ${attribute}>${rows}</select>`;
	}

	renderPortSelect(attribute, ports) {
		const rows = ports
			.map(([portName, spec]) => {
				return `<option value="${this.escape(portName)}">${this.escape(portName)} · ${this.escape(spec.type || "JSON")}</option>`;
			})
			.join("");
		return `<select class="form-control input-xs" ${attribute}>${rows}</select>`;
	}

	renderEdgeList() {
		if (!this.$edgeList) {
			return;
		}
		if (!this.edges.length) {
			this.$edgeList.html(`<div class="slow-ai-canvas__empty">${__("No edges")}</div>`);
			return;
		}
		const rows = this.edges
			.map((edge) => {
				return `<div class="slow-ai-canvas__edge-row">
					<div>${this.escape(edge.source)}.${this.escape(edge.source_port)} → ${this.escape(edge.target)}.${this.escape(edge.target_port)}</div>
					<button class="btn btn-xs btn-default" type="button" data-action="delete-edge" data-edge-id="${this.escape(edge.id)}">${__("Delete")}</button>
				</div>`;
			})
			.join("");
		this.$edgeList.html(`<div class="slow-ai-canvas__editor-subhead">${__("Edges")}</div>${rows}`);
	}

	renderDraftWarnings() {
		if (!this.$draftWarnings) {
			return;
		}
		const warnings = this.draftWarnings();
		if (!warnings.length) {
			this.$draftWarnings.html(`<div class="slow-ai-canvas__draft-ok">${__("Draft checks passed")}</div>`);
			return;
		}
		this.$draftWarnings.html(
			warnings
				.map((warning) => `<div class="slow-ai-canvas__draft-warning">${this.escape(warning)}</div>`)
				.join("")
		);
	}

	draftWarnings() {
		const warnings = [];
		const seenNodeIds = new Set();
		const nodeById = {};
		this.nodes.forEach((node) => {
			if (seenNodeIds.has(node.id)) {
				warnings.push(__("Duplicate node id: {0}", [node.id]));
			}
			seenNodeIds.add(node.id);
			nodeById[node.id] = node;
			const metadata = this.nodeMetadata(node);
			if (!metadata) {
				warnings.push(__("Unknown node type: {0}", [node.type]));
				return;
			}
			Object.entries(metadata.config_schema || {}).forEach(([fieldname, spec]) => {
				if (spec.required && this.isMissing(node.config && node.config[fieldname])) {
					warnings.push(__("Missing required config: {0}.{1}", [node.id, fieldname]));
				}
			});
			Object.entries(metadata.input_schema || {}).forEach(([portName, spec]) => {
				const connected = this.edges.some((edge) => edge.target === node.id && edge.target_port === portName);
				if (spec.required && !connected) {
					warnings.push(__("Missing required input: {0}.{1}", [node.id, portName]));
				}
			});
			if (metadata.is_output_node) {
				const connected = this.edges.some((edge) => edge.target === node.id);
				if (!connected) {
					warnings.push(__("Output node requires an input: {0}", [node.id]));
				}
			}
		});
		this.edges.forEach((edge) => {
			const sourceNode = nodeById[edge.source];
			const targetNode = nodeById[edge.target];
			if (!sourceNode) {
				warnings.push(__("Edge source does not exist: {0}", [edge.source]));
				return;
			}
			if (!targetNode) {
				warnings.push(__("Edge target does not exist: {0}", [edge.target]));
				return;
			}
			if (!this.outputPorts(sourceNode).some(([portName]) => portName === edge.source_port)) {
				warnings.push(__("Source port does not exist: {0}.{1}", [edge.source, edge.source_port]));
			}
			if (!this.inputPorts(targetNode).some(([portName]) => portName === edge.target_port)) {
				warnings.push(__("Target port does not exist: {0}.{1}", [edge.target, edge.target_port]));
			}
			if (
				this.outputPorts(sourceNode).some(([portName]) => portName === edge.source_port) &&
				this.inputPorts(targetNode).some(([portName]) => portName === edge.target_port) &&
				!this.portsCompatible(sourceNode, edge.source_port, targetNode, edge.target_port)
			) {
				warnings.push(__("Port types do not match: {0}.{1} to {2}.{3}", [
					edge.source,
					edge.source_port,
					edge.target,
					edge.target_port,
				]));
			}
		});
		if (!this.nodes.some((node) => this.nodeMetadata(node) && this.nodeMetadata(node).is_output_node)) {
			warnings.push(__("At least one output node is required."));
		}
		return warnings;
	}

	isMissing(value) {
		return value === null || value === undefined || value === "";
	}

	clearRunMonitor() {
		if (this.$summary) {
			this.$summary.html(`<div class="slow-ai-canvas__empty">${__("No run selected")}</div>`);
		}
		this.clearHistoryPanels();
	}

	clearHistoryPanels() {
		if (this.$history) {
			this.$history.html(`<div class="slow-ai-canvas__empty">${__("No run history")}</div>`);
		}
		if (this.$providerJobs) {
			this.$providerJobs.html(`<div class="slow-ai-canvas__empty">${__("No provider jobs")}</div>`);
		}
		if (this.$ledgerSummary) {
			this.$ledgerSummary.html(`<div class="slow-ai-canvas__empty">${__("No ledger entries")}</div>`);
		}
		if (this.$runErrors) {
			this.$runErrors.html(`<div class="slow-ai-canvas__empty">${__("No errors")}</div>`);
		}
		if (this.$runTimeline) {
			this.$runTimeline.html(`<div class="slow-ai-canvas__empty">${__("No timeline events")}</div>`);
		}
	}

	renderRunSummary(status) {
		const nodeStatusOrder = ["PENDING", "READY", "RUNNING", "WAITING_PROVIDER", "SUCCEEDED", "FAILED", "SKIPPED", "CANCELLED"];
		const nodeCounts = (status.node_runs || []).reduce((counts, nodeRun) => {
			counts[nodeRun.status] = (counts[nodeRun.status] || 0) + 1;
			return counts;
		}, {});
		const counts = nodeStatusOrder
			.filter((key) => nodeCounts[key])
			.map((key) => `<span class="slow-ai-canvas__status-count">${this.escape(key)} ${nodeCounts[key]}</span>`)
			.join("");
		const nodeRows = (status.node_runs || [])
			.map((nodeRun) => this.renderNodeRunRow(nodeRun))
			.join("");
		this.$summary.html(`
			<div class="slow-ai-canvas__run-card">
				<div class="slow-ai-canvas__monitor-title">${__("Workflow Status")}</div>
				<div class="slow-ai-canvas__metric">${__("Workflow")}: ${this.escape(status.workflow)}</div>
				<div class="slow-ai-canvas__metric">${__("Run")}: ${this.escape(status.workflow_run)}</div>
				<div class="slow-ai-canvas__metric">${__("Status")}: ${this.statusBadge(status.status)}</div>
				<div class="slow-ai-canvas__metric">${__("Queued")}: ${this.escape(this.formatTime(status.queued_at))}</div>
				<div class="slow-ai-canvas__metric">${__("Started")}: ${this.escape(this.formatTime(status.started_at))}</div>
				<div class="slow-ai-canvas__metric">${__("Completed")}: ${this.escape(this.formatTime(status.completed_at))}</div>
				<div class="slow-ai-canvas__status-counts">${counts || `<span class="slow-ai-canvas__status-count">${__("No node status")}</span>`}</div>
			</div>
			<div class="slow-ai-canvas__monitor-title">${__("Node Status")}</div>
			${nodeRows || `<div class="slow-ai-canvas__empty">${__("No node runs")}</div>`}
		`);
	}

	renderNodeRunRow(nodeRun) {
		const cost = this.money(nodeRun.cost_usd);
		return `<div class="slow-ai-canvas__monitor-row" data-node-run-status="${this.escape(nodeRun.status)}">
			<div>
				<div class="slow-ai-canvas__monitor-row-title">${this.escape(nodeRun.node_id)}</div>
				<div class="slow-ai-canvas__monitor-row-meta">${this.escape(nodeRun.node_type || "")}</div>
				${nodeRun.provider_job ? `<div class="slow-ai-canvas__monitor-row-meta">${__("Provider Job")}: ${this.escape(nodeRun.provider_job)}</div>` : ""}
			</div>
			<div class="slow-ai-canvas__monitor-row-side">
				${this.statusBadge(nodeRun.status)}
				<div>${this.escape(cost)}</div>
			</div>
		</div>`;
	}

	renderHistory(history) {
		const assets = history.assets || [];
		const ledger = history.ledger || [];
		const jobs = history.provider_jobs || [];
		const nodeRuns = history.node_runs || [];
		const run = history.run || {};
		this.$history.html(`
			<div class="slow-ai-canvas__history-item">${__("Workflow")}: ${this.escape(run.workflow || "")}</div>
			<div class="slow-ai-canvas__history-item">${__("Run")}: ${this.escape(run.workflow_run || this.workflowRun || "")}</div>
			<div class="slow-ai-canvas__history-item">${__("Nodes")}: ${nodeRuns.length}</div>
			<div class="slow-ai-canvas__history-item">${__("Provider Jobs")}: ${jobs.length}</div>
			<div class="slow-ai-canvas__history-item">${__("Assets")}: ${assets.length}</div>
			<div class="slow-ai-canvas__history-item">${__("Ledger Entries")}: ${ledger.length}</div>
		`);
		this.renderProviderJobs(jobs);
		this.renderLedgerSummary(ledger);
		this.renderRunErrors(run, nodeRuns, jobs);
		this.renderRunTimeline(run, nodeRuns, jobs, assets);
		this.renderAssetOutputs(assets);
	}

	renderProviderJobs(jobs) {
		if (!this.$providerJobs) {
			return;
		}
		if (!jobs.length) {
			this.$providerJobs.html(`<div class="slow-ai-canvas__empty">${__("No provider jobs")}</div>`);
			return;
		}
		this.$providerJobs.html(
			jobs
				.map((job) => {
					return `<div class="slow-ai-canvas__monitor-row" data-provider-job-status="${this.escape(job.status)}">
						<div>
							<div class="slow-ai-canvas__monitor-row-title">${this.escape(job.name)}</div>
							<div class="slow-ai-canvas__monitor-row-meta">${this.escape(job.provider || "")} / ${this.escape(job.model || "")}</div>
							<div class="slow-ai-canvas__monitor-row-meta">${__("Node Run")}: ${this.escape(job.node_run || "")}</div>
							<div class="slow-ai-canvas__monitor-row-meta">${__("Submitted")}: ${this.escape(this.formatTime(job.submitted_at))}</div>
							<div class="slow-ai-canvas__monitor-row-meta">${__("Completed")}: ${this.escape(this.formatTime(job.completed_at))}</div>
							${this.safeErrorMessage(job.error) ? `<div class="slow-ai-canvas__safe-error">${this.escape(this.safeErrorMessage(job.error))}</div>` : ""}
						</div>
						<div class="slow-ai-canvas__monitor-row-side">
							${this.statusBadge(job.status)}
							<div>${this.escape(this.money(job.cost_usd))}</div>
						</div>
					</div>`;
				})
				.join("")
		);
	}

	renderLedgerSummary(ledger) {
		if (!this.$ledgerSummary) {
			return;
		}
		if (!ledger.length) {
			this.$ledgerSummary.html(`<div class="slow-ai-canvas__empty">${__("No ledger entries")}</div>`);
			return;
		}
		const totals = ledger.reduce(
			(summary, row) => {
				const amount = Number(row.amount_usd || 0);
				if (row.ledger_type === "CREDIT") {
					summary.credit += amount;
				} else if (row.ledger_type === "DEBIT") {
					summary.debit += amount;
				} else {
					summary.adjustment += amount;
				}
				summary.currency = row.currency || summary.currency;
				return summary;
			},
			{ credit: 0, debit: 0, adjustment: 0, currency: "USD" }
		);
		const net = totals.credit - totals.debit + totals.adjustment;
		const rows = ledger
			.map((row) => {
				return `<div class="slow-ai-canvas__ledger-row">
					<span>${this.escape(row.ledger_type)} · ${this.escape(row.name)}</span>
					<strong>${this.escape(this.money(row.amount_usd, row.currency))}</strong>
				</div>`;
			})
			.join("");
		this.$ledgerSummary.html(`
			<div class="slow-ai-canvas__metric">${__("Debit")}: ${this.escape(this.money(totals.debit, totals.currency))}</div>
			<div class="slow-ai-canvas__metric">${__("Credit")}: ${this.escape(this.money(totals.credit, totals.currency))}</div>
			<div class="slow-ai-canvas__metric">${__("Adjustment")}: ${this.escape(this.money(totals.adjustment, totals.currency))}</div>
			<div class="slow-ai-canvas__metric">${__("Net")}: ${this.escape(this.money(net, totals.currency))}</div>
			${rows}
		`);
	}

	renderRunErrors(run, nodeRuns, jobs) {
		if (!this.$runErrors) {
			return;
		}
		const errors = [];
		const runError = this.safeErrorMessage(run && run.error);
		if (runError) {
			errors.push(`${__("Workflow")}: ${runError}`);
		}
		nodeRuns.forEach((nodeRun) => {
			const message = this.safeErrorMessage(nodeRun.error);
			if (message) {
				errors.push(`${nodeRun.node_id || nodeRun.name}: ${message}`);
			}
		});
		jobs.forEach((job) => {
			const message = this.safeErrorMessage(job.error);
			if (message) {
				errors.push(`${job.name}: ${message}`);
			}
		});
		if (!errors.length) {
			this.$runErrors.html(`<div class="slow-ai-canvas__empty">${__("No errors")}</div>`);
			return;
		}
		this.$runErrors.html(
			errors
				.map((message) => `<div class="slow-ai-canvas__safe-error">${this.escape(message)}</div>`)
				.join("")
		);
	}

	renderRunTimeline(run, nodeRuns, jobs, assets) {
		if (!this.$runTimeline) {
			return;
		}
		const events = [];
		if (run && run.queued_at) {
			events.push({ label: __("Workflow queued"), at: run.queued_at, detail: run.workflow_run });
		} else if (run && run.workflow_run) {
			events.push({ label: __("Workflow queued"), at: "", detail: run.workflow_run });
		}
		nodeRuns.forEach((nodeRun) => {
			if (nodeRun.started_at) {
				events.push({ label: __("Node started"), at: nodeRun.started_at, detail: `${nodeRun.node_id} · ${nodeRun.status}` });
			}
		});
		jobs.forEach((job) => {
			if (job.submitted_at || ["SUBMITTED", "WAITING_PROVIDER", "SUCCEEDED", "FAILED", "CANCELLED", "EXPIRED"].includes(job.status)) {
				events.push({ label: __("Provider submitted"), at: job.submitted_at, detail: `${job.name} · ${job.status}` });
			}
			if (job.completed_at || ["SUCCEEDED", "FAILED", "CANCELLED", "EXPIRED"].includes(job.status)) {
				events.push({ label: __("Provider completed"), at: job.completed_at, detail: `${job.name} · ${job.status}` });
			}
		});
		assets.forEach((asset) => {
			events.push({ label: __("Asset created"), at: "", detail: `${asset.asset_type} · ${asset.name}` });
		});
		if (run && (run.completed_at || this.isTerminalStatus(run.status))) {
			events.push({ label: run.status === "SUCCEEDED" ? __("Run completed") : __("Run failed"), at: run.completed_at, detail: run.status });
		}
		if (!events.length) {
			this.$runTimeline.html(`<div class="slow-ai-canvas__empty">${__("No timeline events")}</div>`);
			return;
		}
		this.$runTimeline.html(
			events
				.map((event) => {
					return `<div class="slow-ai-canvas__timeline-row">
						<div class="slow-ai-canvas__timeline-dot"></div>
						<div>
							<div class="slow-ai-canvas__monitor-row-title">${this.escape(event.label)}</div>
							<div class="slow-ai-canvas__monitor-row-meta">${this.escape(this.formatTime(event.at))}</div>
							<div class="slow-ai-canvas__monitor-row-meta">${this.escape(event.detail || "")}</div>
						</div>
					</div>`;
				})
				.join("")
		);
	}

	renderAssetOutputs(assets) {
		if (!this.$assets) {
			return Promise.resolve();
		}
		if (!assets || !assets.length) {
			this.$assets.html(`<div class="slow-ai-canvas__empty">${__("No assets yet")}</div>`);
			return Promise.resolve();
		}
		this.$assets.html(`<div class="slow-ai-canvas__empty">${__("Loading assets")}</div>`);
		return Promise.all(
			assets.map((asset) =>
				frappe.call("slow_ai.api.assets.view", { asset: asset.name }).then((response) => response.message)
			)
		).then((viewedAssets) => {
			const html = viewedAssets.map((asset) => this.renderAssetCard(asset)).join("");
			this.$assets.html(html);
		});
	}

	renderAssetCard(asset) {
		const url = this.assetUrl(asset);
		const urlAttr = this.escape(url);
		const openButton = url
			? `<a class="btn btn-xs btn-default" href="${urlAttr}" target="_blank" rel="noopener" data-action="open-asset">${__("Open Asset")}</a>`
			: `<button class="btn btn-xs btn-default" type="button" disabled>${__("Open Asset")}</button>`;
		const copyButton = url
			? `<button class="btn btn-xs btn-default" type="button" data-action="copy-asset-url" data-asset-name="${this.escape(asset.name)}">${__("Copy URL")}</button>`
			: `<button class="btn btn-xs btn-default" type="button" disabled>${__("Copy URL")}</button>`;
		return `<div class="slow-ai-canvas__asset-card" data-asset-name="${this.escape(asset.name)}" data-asset-url="${urlAttr}">
			<div class="slow-ai-canvas__asset-preview">${this.renderAssetPreview(asset, url)}</div>
			<div class="slow-ai-canvas__asset-body">
				<div class="slow-ai-canvas__asset-title">${this.escape(asset.name)}</div>
				<div class="slow-ai-canvas__asset-meta-grid">
					${this.renderAssetMetaRow(__("Type"), asset.asset_type)}
					${this.renderAssetMetaRow(__("MIME"), asset.mime_type)}
					${this.renderAssetMetaRow(__("Workflow Run"), asset.source_workflow_run)}
					${this.renderAssetMetaRow(__("Node Run"), asset.source_node_run)}
					${this.renderAssetMetaRow(__("Provider Job"), asset.source_provider_job)}
					${this.renderAssetMetaRow(__("Size"), this.assetSize(asset))}
					${this.renderAssetMetaRow(__("Duration"), this.assetDuration(asset))}
					${this.renderAssetMetaRow(__("Created"), this.formatTime(asset.created))}
					${this.renderAssetMetaRow(__("Modified"), this.formatTime(asset.modified))}
				</div>
				<div class="slow-ai-canvas__asset-actions">
					${openButton}
					${copyButton}
					<button class="btn btn-xs btn-default" type="button" data-action="refresh-asset" data-asset-name="${this.escape(asset.name)}">${__("Refresh Asset")}</button>
				</div>
			</div>
		</div>`;
	}

	renderAssetPreview(asset, url) {
		const assetType = String(asset.asset_type || "").toUpperCase();
		if (assetType === "IMAGE" && url) {
			return `<img class="slow-ai-canvas__asset-media" src="${this.escape(url)}" alt="${this.escape(asset.name)}">`;
		}
		if (assetType === "VIDEO" && url) {
			return `<video class="slow-ai-canvas__asset-media" src="${this.escape(url)}" controls preload="metadata"></video>`;
		}
		if (assetType === "AUDIO" && url) {
			return `<audio class="slow-ai-canvas__asset-audio" src="${this.escape(url)}" controls preload="metadata"></audio>`;
		}
		if (assetType === "JSON" || assetType === "TEXT") {
			return `<pre class="slow-ai-canvas__asset-text-preview">${this.escape(this.assetTextSummary(asset))}</pre>`;
		}
		return `<div class="slow-ai-canvas__asset-placeholder">${this.escape(assetType || __("ASSET"))}</div>`;
	}

	renderAssetMetaRow(label, value) {
		const display = value === null || value === undefined || value === "" ? "-" : value;
		return `<div class="slow-ai-canvas__asset-meta-row">
			<span>${this.escape(label)}</span>
			<strong>${this.escape(display)}</strong>
		</div>`;
	}

	assetUrl(asset) {
		return (asset && (asset.file || asset.url)) || "";
	}

	assetSize(asset) {
		if (asset && asset.width && asset.height) {
			return `${asset.width} x ${asset.height}`;
		}
		return "";
	}

	assetDuration(asset) {
		if (!asset || !asset.duration_seconds) {
			return "";
		}
		return `${Number(asset.duration_seconds).toFixed(2)}s`;
	}

	assetTextSummary(asset) {
		const metadata = (asset && asset.metadata) || {};
		const candidate =
			metadata.text ||
			metadata.content ||
			metadata.value ||
			metadata.json ||
			(Object.keys(metadata).length ? metadata : "");
		if (!candidate) {
			return __("No preview content");
		}
		if (typeof candidate === "string") {
			return candidate.slice(0, 1000);
		}
		return JSON.stringify(candidate, null, 2).slice(0, 1000);
	}

	refreshAssetCard(assetName) {
		if (!assetName) {
			return Promise.resolve();
		}
		const $card = this.$assets.find(`[data-asset-name="${this.escapeSelector(assetName)}"]`);
		$card.addClass("slow-ai-canvas__asset-card--loading");
		return frappe.call("slow_ai.api.assets.view", { asset: assetName }).then((response) => {
			const asset = response.message;
			const html = this.renderAssetCard(asset);
			if ($card.length) {
				$card.replaceWith(html);
			}
			this.setStatus(__("Refreshed asset {0}", [assetName]));
		});
	}

	copyAssetUrl(assetName) {
		const $card = this.$assets.find(`[data-asset-name="${this.escapeSelector(assetName)}"]`);
		const url = $card.attr("data-asset-url") || "";
		if (!url) {
			return;
		}
		if (navigator.clipboard && navigator.clipboard.writeText) {
			navigator.clipboard.writeText(url).then(() => this.setStatus(__("Copied asset URL")));
			return;
		}
		const textarea = document.createElement("textarea");
		textarea.value = url;
		document.body.appendChild(textarea);
		textarea.select();
		document.execCommand("copy");
		document.body.removeChild(textarea);
		this.setStatus(__("Copied asset URL"));
	}

	setStatus(message) {
		this.$status.text(message);
	}

	statusBadge(status) {
		const value = status || __("UNKNOWN");
		return `<span class="slow-ai-canvas__status-badge" data-status="${this.escape(value)}">${this.escape(value)}</span>`;
	}

	formatTime(value) {
		if (!value) {
			return "-";
		}
		return String(value);
	}

	money(value, currency) {
		const amount = Number(value || 0);
		const code = currency || "USD";
		return `${code} ${amount.toFixed(4)}`;
	}

	safeErrorMessage(error) {
		if (!error) {
			return "";
		}
		if (typeof error === "string") {
			return this.sanitizeErrorText(error);
		}
		if (typeof error !== "object") {
			return __("Error details captured on server.");
		}
		const parts = [];
		["message", "error", "status", "code", "type"].forEach((key) => {
			const value = error[key];
			if (value === null || value === undefined || typeof value === "object") {
				return;
			}
			parts.push(`${key}: ${this.sanitizeErrorText(value)}`);
		});
		return parts.length ? parts.join(" · ") : __("Error details captured on server.");
	}

	sanitizeErrorText(value) {
		return String(value)
			.replace(/https?:\/\/\S+/gi, "[link hidden]")
			.replace(/(api[_-]?key|authorization|bearer|secret|token)\s*[:=]\s*[^,\s]+/gi, "$1: [redacted]")
			.slice(0, 240);
	}

	escapeSelector(value) {
		if (window.CSS && window.CSS.escape) {
			return window.CSS.escape(value || "");
		}
		return String(value || "").replace(/["\\]/g, "\\$&");
	}

	escape(value) {
		const text = value === null || value === undefined ? "" : String(value);
		if (frappe.utils && frappe.utils.escape_html) {
			return frappe.utils.escape_html(text);
		}
		return text.replace(/[&<>"']/g, (char) => ({
			"&": "&amp;",
			"<": "&lt;",
			">": "&gt;",
			'"': "&quot;",
			"'": "&#39;",
		}[char]));
	}
}
