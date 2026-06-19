frappe.pages["slow-ai-tools"].on_page_load = function (wrapper) {
	const tools = new SlowAiToolsPage(wrapper);
	$(wrapper).data("slow-ai-tools", tools);
};

frappe.pages["slow-ai-tools"].on_page_show = function (wrapper) {
	const tools = $(wrapper).data("slow-ai-tools");
	if (tools) {
		tools.show();
	}
};

class SlowAiToolsPage {
	constructor(wrapper) {
		this.wrapper = wrapper;
		this.page = frappe.ui.make_app_page({
			parent: wrapper,
			title: __("Slow AI Tools"),
			single_column: true,
		});
		this.templates = [];
		this.template = null;
		this.workflow = null;
		this.workflowRun = null;
		this.pollTimer = null;
		this.makeBody();
		this.bindEvents();
	}

	makeBody() {
		this.page.main.empty();
		$(frappe.render_template("slow_ai_tools")).appendTo(this.page.main);
		this.$root = this.page.main.find("[data-page='slow-ai-tools']");
		this.$project = this.$root.find("[data-role='project']");
		this.$balance = this.$root.find("[data-role='balance']");
		this.$templates = this.$root.find("[data-role='template-list']");
		this.$templateDetail = this.$root.find("[data-role='template-detail']");
		this.$form = this.$root.find("[data-role='tool-form']");
		this.$providerWarning = this.$root.find("[data-role='provider-warning']");
		this.$status = this.$root.find("[data-role='status']");
		this.$summary = this.$root.find("[data-role='run-summary']");
		this.$history = this.$root.find("[data-role='run-history']");
		this.$assets = this.$root.find("[data-role='asset-output']");
	}

	bindEvents() {
		this.$root.on("click", "[data-action='refresh-templates']", () => this.loadTemplates());
		this.$root.on("click", "[data-action='select-template']", (event) => {
			this.loadTemplate($(event.currentTarget).attr("data-template-name"));
		});
		this.$root.on("click", "[data-action='refresh-balance']", () => this.refreshBalance());
		this.$root.on("change", "[data-role='project']", () => this.refreshBalance());
		this.$root.on("click", "[data-action='preview-input-asset']", (event) => {
			this.previewInputAsset($(event.currentTarget).attr("data-node-id"));
		});
		this.$root.on("click", "[data-action='create-input-asset']", (event) => {
			this.createInputAsset($(event.currentTarget).attr("data-node-id"));
		});
		this.$root.on("click", "[data-action='run-tool']", () => this.runTool());
		this.$root.on("click", "[data-action='refresh-run']", () => this.refreshRun());
	}

	show() {
		this.loadTemplates();
		this.refreshBalance();
		if (this.workflowRun) {
			this.refreshRun();
		}
	}

	loadTemplates() {
		this.$templates.html(`<div class="slow-ai-tools__empty">${__("Loading templates")}</div>`);
		return frappe.call("slow_ai.api.public_tools.list_templates").then((response) => {
			this.templates = (response.message && response.message.templates) || [];
			this.renderTemplateList();
		});
	}

	renderTemplateList() {
		if (!this.templates.length) {
			this.$templates.html(`<div class="slow-ai-tools__empty">${__("No published templates")}</div>`);
			return;
		}
		this.$templates.html(
			this.templates
				.map((template) => {
					const selected = this.template && this.template.name === template.name ? " is-selected" : "";
					return `<article class="slow-ai-tools__template${selected}" data-template-name="${this.escape(template.name)}">
						<div>
							<h4>${this.escape(template.template_name || template.name)}</h4>
							<div class="slow-ai-tools__muted">${this.escape(template.category || __("Uncategorized"))} · ${this.escape(template.status || "")}</div>
							${template.description ? `<p>${this.escape(template.description)}</p>` : ""}
						</div>
						<button class="btn btn-xs btn-primary" type="button" data-action="select-template" data-template-name="${this.escape(template.name)}">${__("Select")}</button>
					</article>`;
				})
				.join("")
		);
	}

	loadTemplate(templateName) {
		if (!templateName) {
			return Promise.resolve();
		}
		this.setStatus(__("Loading template"));
		return frappe.call("slow_ai.api.public_tools.get_template", { template: templateName }).then((response) => {
			this.template = response.message;
			this.renderTemplateList();
			this.renderSelectedTemplate();
			this.setStatus(__("Ready"));
		});
	}

	renderSelectedTemplate() {
		if (!this.template) {
			this.$templateDetail.html(`<div class="slow-ai-tools__empty">${__("Select a published template")}</div>`);
			this.$form.empty();
			this.$providerWarning.empty();
			return;
		}
		this.$templateDetail.html(`<div class="slow-ai-tools__selected">
			<h3>${this.escape(this.template.template_name || this.template.name)}</h3>
			<div class="slow-ai-tools__muted">${this.escape(this.template.category || __("Uncategorized"))}</div>
			${this.template.description ? `<p>${this.escape(this.template.description)}</p>` : ""}
		</div>`);
		this.renderForm();
		this.renderProviderWarning();
	}

	renderForm() {
		const controls = (this.template.nodes || []).map((node) => this.renderNodeControl(node)).filter(Boolean).join("");
		this.$form.html(controls || `<div class="slow-ai-tools__empty">${__("This template has no editable fields")}</div>`);
	}

	renderNodeControl(node) {
		const config = node.config || {};
		const label = node.label || node.id;
		if (node.type === "text_prompt") {
			return `<label class="slow-ai-tools__field">
				<span>${this.escape(label)}</span>
				<textarea class="form-control" data-node-id="${this.escape(node.id)}" data-config-field="text">${this.escape(config.text || "")}</textarea>
			</label>`;
		}
		if (node.type === "upload_asset") {
			return `<div class="slow-ai-tools__asset-input" data-asset-section="${this.escape(node.id)}">
				<h4>${this.escape(label)}</h4>
				<label class="slow-ai-tools__field">
					<span>${__("Existing Asset")}</span>
					<input class="form-control" type="text" data-node-id="${this.escape(node.id)}" data-config-field="asset" value="${this.escape(config.asset || "")}" placeholder="AI-ASSET-00001">
				</label>
				<label class="slow-ai-tools__field">
					<span>${__("Asset Type")}</span>
					<select class="form-control" data-node-id="${this.escape(node.id)}" data-config-field="asset_type">
						${this.assetTypeOption("IMAGE", config.asset_type)}
						${this.assetTypeOption("VIDEO", config.asset_type)}
						${this.assetTypeOption("AUDIO", config.asset_type)}
						${this.assetTypeOption("MASK", config.asset_type)}
					</select>
				</label>
				<label class="slow-ai-tools__field">
					<span>${__("New Asset URL")}</span>
					<input class="form-control" type="text" data-upload-url="${this.escape(node.id)}" placeholder="https://example.invalid/input.png">
				</label>
				<label class="slow-ai-tools__field">
					<span>${__("New Asset File Reference")}</span>
					<input class="form-control" type="text" data-upload-file="${this.escape(node.id)}" placeholder="/files/input.png">
				</label>
				<label class="slow-ai-tools__field">
					<span>${__("MIME Type")}</span>
					<input class="form-control" type="text" data-upload-mime="${this.escape(node.id)}" value="${this.escape(config.mime_type || "")}" placeholder="image/png">
				</label>
				<div class="slow-ai-tools__inline-actions">
					<button class="btn btn-xs btn-default" type="button" data-action="preview-input-asset" data-node-id="${this.escape(node.id)}">${__("Preview Asset")}</button>
					<button class="btn btn-xs btn-default" type="button" data-action="create-input-asset" data-node-id="${this.escape(node.id)}">${__("Create Asset")}</button>
				</div>
				<div data-asset-preview="${this.escape(node.id)}"></div>
			</div>`;
		}
		return "";
	}

	assetTypeOption(assetType, selectedAssetType) {
		const selected = assetType === String(selectedAssetType || "") ? "selected" : "";
		return `<option value="${this.escape(assetType)}" ${selected}>${this.escape(assetType)}</option>`;
	}

	renderProviderWarning() {
		const providerNodes = this.providerNodes();
		if (!providerNodes.length) {
			this.$providerWarning.html(`<div class="slow-ai-tools__empty">${__("No external provider nodes")}</div>`);
			return Promise.resolve();
		}
		this.$providerWarning.html(`<div class="slow-ai-tools__warning">${__("This workflow may call an external provider and spend credits.")}</div>`);
		return this.loadModelMetadata(providerNodes).then((models) => {
			const rows = providerNodes.map((node) => this.providerWarningRow(node, models)).join("");
			this.$providerWarning.html(`<div class="slow-ai-tools__warning">
				<strong>${__("This workflow may call an external provider and spend credits.")}</strong>
				${rows}
			</div>`);
		});
	}

	providerWarningRow(node, models) {
		const config = node.config || {};
		const model = config.model || "";
		const metadata = models[model] || {};
		const cost = metadata.pricing_known
			? `${metadata.currency || "USD"} ${metadata.estimated_cost_usd} / ${metadata.pricing_unit || "run"}`
			: __("cost unknown");
		return `<div class="slow-ai-tools__provider-row">
			<span>${this.escape(node.label || node.id)}</span>
			<strong>${this.escape(config.provider || "")} / ${this.escape(model)} · ${this.escape(cost)}</strong>
		</div>`;
	}

	providerNodes() {
		if (!this.template) {
			return [];
		}
		return (this.template.nodes || []).filter((node) => node.type && node.type.indexOf("provider_") === 0);
	}

	loadModelMetadata(providerNodes) {
		const modelIds = providerNodes
			.map((node) => node.config && node.config.model)
			.filter((model) => model);
		if (!modelIds.length) {
			return Promise.resolve({});
		}
		return frappe
			.call("slow_ai.api.models.get_model_metadata", { model_ids: modelIds })
			.then((response) => (response.message && response.message.models) || {});
	}

	refreshBalance() {
		const project = this.projectName();
		if (!project) {
			this.$balance.text(__("Enter a project to view balance"));
			return Promise.resolve();
		}
		return frappe
			.call("slow_ai.api.billing.get_balance", { project })
			.then((response) => {
				const balance = response.message || {};
				this.$balance.text(`${__("Balance")}: ${this.money(balance.balance_usd, balance.currency)}`);
			})
			.catch(() => {
				this.$balance.text(__("Balance unavailable"));
			});
	}

	runTool() {
		if (!this.template) {
			frappe.msgprint(__("Select a published template before running."));
			return Promise.resolve();
		}
		const project = this.projectName();
		if (!project) {
			frappe.msgprint(__("Enter an AI Project before running."));
			return Promise.resolve();
		}
		return this.confirmProviderRun().then((confirmed) => {
			if (!confirmed) {
				this.setStatus(__("Run cancelled"));
				return null;
			}
			const values = this.collectFormValues();
			const title = `${this.template.template_name || this.template.name} Run`;
			this.setStatus(__("Creating workflow draft"));
			return frappe
				.call("slow_ai.api.public_tools.create_workflow_from_template", {
					template: this.template.name,
					project,
					title,
				})
				.then((response) => {
					const draft = response.message;
					const nodes = this.applyFormValues(draft.nodes || [], values);
					return frappe.call("slow_ai.api.workflows.save_workflow", {
						workflow: draft.name,
						project,
						title: draft.title,
						nodes,
						edges: draft.edges || [],
						layout: draft.layout || {},
					});
				})
				.then((response) => {
					this.workflow = response.message.name;
					this.setStatus(__("Starting run"));
					return frappe.call("slow_ai.api.runs.start_run", { workflow: this.workflow });
				})
				.then((response) => {
					const result = response.message;
					this.workflowRun = result.workflow_run;
					this.setStatus(__("Queued {0}", [result.workflow_run]));
					this.startPolling();
					return this.refreshRun();
				});
		});
	}

	confirmProviderRun() {
		const providerNodes = this.providerNodes();
		if (!providerNodes.length) {
			return Promise.resolve(true);
		}
		return this.loadModelMetadata(providerNodes).then((models) => {
			const rows = providerNodes.map((node) => this.providerWarningRow(node, models)).join("");
			const message = `<p>${__("This workflow may call an external provider and spend credits.")}</p>${rows}`;
			return new Promise((resolve) => {
				frappe.confirm(message, () => resolve(true), () => resolve(false));
			});
		});
	}

	collectFormValues() {
		const values = {};
		this.$form.find("[data-node-id][data-config-field]").each((index, element) => {
			const nodeId = $(element).attr("data-node-id");
			const field = $(element).attr("data-config-field");
			values[nodeId] = values[nodeId] || {};
			values[nodeId][field] = $(element).val();
		});
		return values;
	}

	applyFormValues(nodes, values) {
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

	previewInputAsset(nodeId) {
		const assetName = this.assetSection(nodeId).find("[data-config-field='asset']").val();
		if (!assetName) {
			frappe.msgprint(__("Enter an asset name before previewing."));
			return Promise.resolve();
		}
		return frappe.call("slow_ai.api.assets.view", { asset: assetName }).then((response) => {
			this.renderInputAssetPreview(nodeId, response.message);
		});
	}

	createInputAsset(nodeId) {
		const project = this.projectName();
		if (!project) {
			frappe.msgprint(__("Enter an AI Project before creating an asset."));
			return Promise.resolve();
		}
		const $section = this.assetSection(nodeId);
		const assetType = $section.find("[data-config-field='asset_type']").val() || "IMAGE";
		const url = $section.find(`[data-upload-url="${this.escapeSelector(nodeId)}"]`).val() || "";
		const file = $section.find(`[data-upload-file="${this.escapeSelector(nodeId)}"]`).val() || "";
		const mimeType = $section.find(`[data-upload-mime="${this.escapeSelector(nodeId)}"]`).val() || "";
		if (!url && !file) {
			frappe.msgprint(__("Provide a URL or file reference."));
			return Promise.resolve();
		}
		return frappe
			.call("slow_ai.api.assets.upload", {
				project,
				asset_type: assetType,
				url: url || null,
				file: file || null,
				mime_type: mimeType || null,
				metadata: { source: "public_tool_page" },
			})
			.then((response) => {
				const asset = response.message;
				$section.find("[data-config-field='asset']").val(asset.name);
				$section.find("[data-config-field='asset_type']").val(asset.asset_type);
				this.renderInputAssetPreview(nodeId, asset);
				this.setStatus(__("Created asset {0}", [asset.name]));
			});
	}

	renderInputAssetPreview(nodeId, asset) {
		this.assetSection(nodeId).find(`[data-asset-preview="${this.escapeSelector(nodeId)}"]`).html(this.renderAssetCard(asset));
	}

	assetSection(nodeId) {
		return this.$form.find(`[data-asset-section="${this.escapeSelector(nodeId)}"]`);
	}

	refreshRun() {
		if (!this.workflowRun) {
			this.$summary.html(`<div class="slow-ai-tools__empty">${__("No run selected")}</div>`);
			this.$history.empty();
			this.$assets.empty();
			return Promise.resolve();
		}
		return frappe.call("slow_ai.api.runs.get_run_status", { workflow_run: this.workflowRun }).then((response) => {
			const status = response.message;
			this.renderRunStatus(status);
			if (this.isTerminal(status.status)) {
				this.stopPolling();
			}
			return this.refreshHistory();
		});
	}

	refreshHistory() {
		return frappe.call("slow_ai.api.runs.get_history", { workflow_run: this.workflowRun }).then((response) => {
			const history = response.message;
			this.renderHistory(history);
			return this.renderOutputAssets(history);
		});
	}

	renderRunStatus(status) {
		const nodeRows = (status.node_runs || []).map((nodeRun) => {
			return `<div class="slow-ai-tools__row">
				<span>${this.escape(nodeRun.node_id)} · ${this.escape(nodeRun.node_type || "")}</span>
				<strong>${this.escape(nodeRun.status)}</strong>
			</div>`;
		}).join("");
		this.$summary.html(`<div class="slow-ai-tools__run-card">
			<div class="slow-ai-tools__row"><span>${__("Run")}</span><strong>${this.escape(status.workflow_run)}</strong></div>
			<div class="slow-ai-tools__row"><span>${__("Status")}</span><strong>${this.escape(status.status)}</strong></div>
			${nodeRows}
		</div>`);
	}

	renderHistory(history) {
		const jobs = history.provider_jobs || [];
		const ledger = history.ledger || [];
		this.$history.html(`<div class="slow-ai-tools__run-card">
			<div class="slow-ai-tools__row"><span>${__("Nodes")}</span><strong>${(history.node_runs || []).length}</strong></div>
			<div class="slow-ai-tools__row"><span>${__("Provider Tasks")}</span><strong>${jobs.length}</strong></div>
			<div class="slow-ai-tools__row"><span>${__("Cost Entries")}</span><strong>${ledger.length}</strong></div>
			${this.renderSafeErrors(history)}
		</div>`);
	}

	renderSafeErrors(history) {
		const messages = [];
		const runError = this.safeErrorMessage(history.run && history.run.error);
		if (runError) {
			messages.push(runError);
		}
		(history.node_runs || []).forEach((nodeRun) => {
			const message = this.safeErrorMessage(nodeRun.error);
			if (message) {
				messages.push(message);
			}
		});
		(history.provider_jobs || []).forEach((job) => {
			const message = this.safeErrorMessage(job.error);
			if (message) {
				messages.push(message);
			}
		});
		return messages.map((message) => `<div class="slow-ai-tools__error">${this.escape(message)}</div>`).join("");
	}

	renderOutputAssets(history) {
		const assetNames = this.assetNamesFromHistory(history);
		if (!assetNames.length) {
			this.$assets.html(`<div class="slow-ai-tools__empty">${__("No asset outputs yet")}</div>`);
			return Promise.resolve();
		}
		this.$assets.html(`<div class="slow-ai-tools__empty">${__("Loading asset outputs")}</div>`);
		return Promise.all(
			assetNames.map((asset) =>
				frappe.call("slow_ai.api.assets.view", { asset }).then((response) => response.message)
			)
		).then((assets) => {
			this.$assets.html(assets.map((asset) => this.renderAssetCard(asset)).join(""));
		});
	}

	assetNamesFromHistory(history) {
		const names = new Set();
		(history.assets || []).forEach((asset) => {
			if (asset.name) {
				names.add(asset.name);
			}
		});
		(history.node_runs || []).forEach((nodeRun) => {
			this.collectAssetNames(nodeRun.output, names);
		});
		return Array.from(names);
	}

	collectAssetNames(value, names) {
		if (typeof value === "string" && value.indexOf("AI-ASSET-") === 0) {
			names.add(value);
			return;
		}
		if (Array.isArray(value)) {
			value.forEach((item) => this.collectAssetNames(item, names));
			return;
		}
		if (value && typeof value === "object") {
			Object.keys(value).forEach((key) => this.collectAssetNames(value[key], names));
		}
	}

	renderAssetCard(asset) {
		const url = this.assetUrl(asset);
		const preview = this.renderAssetPreview(asset, url);
		const open = url
			? `<a class="btn btn-xs btn-default" href="${this.escape(url)}" target="_blank" rel="noopener">${__("Open Asset")}</a>`
			: "";
		return `<article class="slow-ai-tools__asset-card" data-asset-name="${this.escape(asset.name)}">
			<div class="slow-ai-tools__asset-preview">${preview}</div>
			<div>
				<h4>${this.escape(asset.name)}</h4>
				<div class="slow-ai-tools__muted">${this.escape(asset.asset_type || "")} · ${this.escape(asset.mime_type || "")}</div>
				<div class="slow-ai-tools__muted">${__("Source Run")}: ${this.escape(asset.source_workflow_run || "-")}</div>
				${open}
			</div>
		</article>`;
	}

	renderAssetPreview(asset, url) {
		const assetType = String(asset.asset_type || "").toUpperCase();
		if (assetType === "IMAGE" && url) {
			return `<img src="${this.escape(url)}" alt="${this.escape(asset.name)}">`;
		}
		if (assetType === "VIDEO" && url) {
			return `<video src="${this.escape(url)}" controls preload="metadata"></video>`;
		}
		if (assetType === "AUDIO" && url) {
			return `<audio src="${this.escape(url)}" controls preload="metadata"></audio>`;
		}
		return `<div class="slow-ai-tools__asset-placeholder">${this.escape(assetType || __("ASSET"))}</div>`;
	}

	startPolling() {
		if (this.pollTimer) {
			return;
		}
		this.pollTimer = window.setInterval(() => this.refreshRun(), 3000);
	}

	stopPolling() {
		if (!this.pollTimer) {
			return;
		}
		window.clearInterval(this.pollTimer);
		this.pollTimer = null;
	}

	isTerminal(status) {
		return ["SUCCEEDED", "FAILED", "CANCELLED", "EXPIRED"].includes(status);
	}

	projectName() {
		return String(this.$project.val() || "").trim();
	}

	assetUrl(asset) {
		return (asset && (asset.file || asset.url)) || "";
	}

	money(value, currency) {
		const amount = value === undefined || value === null || value === "" ? "0.0000" : Number(value).toFixed(4);
		return `${currency || "USD"} ${amount}`;
	}

	safeErrorMessage(error) {
		if (!error) {
			return "";
		}
		if (typeof error === "string") {
			return this.sanitizeError(error);
		}
		return this.sanitizeError(error.message || error.error || "Run failed.");
	}

	sanitizeError(value) {
		return String(value || "").replace(/Bearer\s+[A-Za-z0-9._-]+/g, "Bearer [redacted]").slice(0, 240);
	}

	setStatus(message) {
		this.$status.text(message || "");
	}

	escape(value) {
		return String(value === null || value === undefined ? "" : value)
			.replace(/&/g, "&amp;")
			.replace(/</g, "&lt;")
			.replace(/>/g, "&gt;")
			.replace(/"/g, "&quot;")
			.replace(/'/g, "&#039;");
	}

	escapeSelector(value) {
		if (window.CSS && window.CSS.escape) {
			return window.CSS.escape(value);
		}
		return String(value).replace(/["\\]/g, "\\$&");
	}
}
