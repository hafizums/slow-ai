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
		this.$runLibrary = this.$root.find("[data-role='run-library']");
		this.$runDetail = this.$root.find("[data-role='run-detail']");
		this.$members = this.$root.find("[data-role='project-members']");
		this.$memberUser = this.$root.find("[data-role='member-user']");
		this.$memberRole = this.$root.find("[data-role='member-role']");
	}

	bindEvents() {
		this.$root.on("click", "[data-action='refresh-templates']", () => this.loadTemplates());
		this.$root.on("click", "[data-action='select-template']", (event) => {
			this.loadTemplate($(event.currentTarget).attr("data-template-name"));
		});
		this.$root.on("click", "[data-action='refresh-balance']", () => this.refreshBalance());
		this.$root.on("change", "[data-role='project']", () => {
			this.loadMyRuns();
		});
		this.$root.on("click", "[data-action='preview-input-asset']", (event) => {
			this.previewInputAsset($(event.currentTarget).attr("data-node-id"));
		});
		this.$root.on("click", "[data-action='create-input-asset']", (event) => {
			this.createInputAsset($(event.currentTarget).attr("data-node-id"));
		});
		this.$root.on("click", "[data-action='run-tool']", () => this.runTool());
		this.$root.on("click", "[data-action='refresh-run']", () => this.refreshRun());
		this.$root.on("click", "[data-action='refresh-my-runs']", () => this.loadMyRuns());
		this.$root.on("click", "[data-action='open-run-detail']", (event) => {
			this.openRunDetail($(event.currentTarget).attr("data-run-id"));
		});
		this.$root.on("click", "[data-action='create-run-share']", (event) => {
			this.createRunShare($(event.currentTarget).attr("data-run-id"));
		});
		this.$root.on("click", "[data-action='disable-run-share']", (event) => {
			this.disableRunShare($(event.currentTarget).attr("data-share-token"));
		});
		this.$root.on("click", "[data-action='copy-share-link']", (event) => {
			this.copyShareLink($(event.currentTarget).attr("data-share-url"));
		});
		this.$root.on("click", "[data-action='copy-asset-url']", (event) => {
			this.copyAssetUrl($(event.currentTarget).attr("data-asset-url"));
		});
		this.$root.on("click", "[data-action='refresh-project-members']", () => this.loadProjectMembers());
		this.$root.on("click", "[data-action='add-project-member']", () => this.addProjectMember());
		this.$root.on("change", "[data-action='update-project-member-role']", (event) => {
			const member = $(event.currentTarget).attr("data-member-name");
			const role = $(event.currentTarget).val();
			this.updateProjectMemberRole(member, role);
		});
		this.$root.on("click", "[data-action='disable-project-member']", (event) => {
			this.disableProjectMember($(event.currentTarget).attr("data-member-name"));
		});
	}

	show() {
		this.loadTemplates();
		this.loadMyRuns();
		this.refreshBalance();
		this.loadProjectMembers();
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

	loadProjectMembers() {
		const project = this.projectName();
		if (!project) {
			this.$members.html(`<div class="slow-ai-tools__empty">${__("Enter a project to manage members")}</div>`);
			return Promise.resolve();
		}
		this.$members.html(`<div class="slow-ai-tools__empty">${__("Loading members")}</div>`);
		return frappe
			.call("slow_ai.api.projects.list_members", { project })
			.then((response) => {
				const members = (response.message && response.message.members) || [];
				this.renderProjectMembers(members);
			})
			.catch(() => {
				this.$members.html(`<div class="slow-ai-tools__empty">${__("Project member management unavailable")}</div>`);
			});
	}

	renderProjectMembers(members) {
		if (!members.length) {
			this.$members.html(`<div class="slow-ai-tools__empty">${__("No project members")}</div>`);
			return;
		}
		this.$members.html(
			members
				.map((member) => `<article class="slow-ai-tools__member" data-member-name="${this.escape(member.name)}">
					<div>
						<strong>${this.escape(member.user)}</strong>
						<div class="slow-ai-tools__muted">${this.escape(member.status)} · ${this.escape(member.name)}</div>
					</div>
					<select class="form-control input-xs" data-action="update-project-member-role" data-member-name="${this.escape(member.name)}">
						${this.memberRoleOption("OWNER", member.role)}
						${this.memberRoleOption("EDITOR", member.role)}
						${this.memberRoleOption("VIEWER", member.role)}
						${this.memberRoleOption("BILLING", member.role)}
					</select>
					<button class="btn btn-xs btn-default" type="button" data-action="disable-project-member" data-member-name="${this.escape(member.name)}">${__("Disable")}</button>
				</article>`)
				.join("")
		);
	}

	memberRoleOption(role, selectedRole) {
		const selected = role === selectedRole ? "selected" : "";
		return `<option value="${this.escape(role)}" ${selected}>${this.escape(role)}</option>`;
	}

	addProjectMember() {
		const project = this.projectName();
		const user = String(this.$memberUser.val() || "").trim();
		const role = String(this.$memberRole.val() || "VIEWER").trim();
		if (!project || !user) {
			frappe.msgprint(__("Enter a project and user before adding a member."));
			return Promise.resolve();
		}
		return frappe
			.call("slow_ai.api.projects.add_member", { project, user, role })
			.then(() => {
				this.$memberUser.val("");
				this.setStatus(__("Project member saved"));
				return this.loadProjectMembers();
			});
	}

	updateProjectMemberRole(member, role) {
		if (!member || !role) {
			return Promise.resolve();
		}
		return frappe
			.call("slow_ai.api.projects.update_member_role", { member, role })
			.then(() => {
				this.setStatus(__("Project member role updated"));
				return this.loadProjectMembers();
			});
	}

	disableProjectMember(member) {
		if (!member) {
			return Promise.resolve();
		}
		return frappe
			.call("slow_ai.api.projects.disable_member", { member })
			.then(() => {
				this.setStatus(__("Project member disabled"));
				return this.loadProjectMembers();
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
					this.loadMyRuns();
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
		return frappe.call("slow_ai.api.public_tools.get_my_run", { workflow_run: this.workflowRun }).then((response) => {
			const detail = response.message;
			this.renderRunStatus(detail.run || {});
			this.renderHistory(detail);
			if (detail.run && this.isTerminal(detail.run.status)) {
				this.stopPolling();
			}
			return this.renderOutputAssets(detail);
		});
	}

	refreshHistory() {
		return this.refreshRun();
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
		const cost = history.cost_summary || {};
		this.$history.html(`<div class="slow-ai-tools__run-card">
			<div class="slow-ai-tools__row"><span>${__("Nodes")}</span><strong>${(history.node_runs || []).length}</strong></div>
			<div class="slow-ai-tools__row"><span>${__("Provider Tasks")}</span><strong>${jobs.length}</strong></div>
			<div class="slow-ai-tools__row"><span>${__("Cost Entries")}</span><strong>${ledger.length}</strong></div>
			<div class="slow-ai-tools__row"><span>${__("Cost")}</span><strong>${this.money(cost.debits_usd, cost.currency)}</strong></div>
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

	loadMyRuns() {
		const project = this.projectName();
		this.$runLibrary.html(`<div class="slow-ai-tools__empty">${__("Loading runs")}</div>`);
		return frappe
			.call("slow_ai.api.public_tools.list_my_runs", {
				project: project || null,
				limit: 25,
			})
			.then((response) => {
				const runs = (response.message && response.message.runs) || [];
				this.renderRunLibrary(runs);
			});
	}

	renderRunLibrary(runs) {
		if (!runs.length) {
			this.$runLibrary.html(`<div class="slow-ai-tools__empty">${__("No tool runs yet")}</div>`);
			return;
		}
		this.$runLibrary.html(
			runs
				.map((run) => {
					const cost = run.cost_summary || {};
					const provider = run.provider_summary || {};
					const shareActions = this.renderShareActions(run, false);
					return `<article class="slow-ai-tools__run-card" data-run-id="${this.escape(run.workflow_run)}">
						<div class="slow-ai-tools__row"><span>${__("Run")}</span><strong>${this.escape(run.workflow_run)}</strong></div>
						<div class="slow-ai-tools__row"><span>${__("Title")}</span><strong>${this.escape(run.workflow_title || run.workflow || "")}</strong></div>
						<div class="slow-ai-tools__row"><span>${__("Project")}</span><strong>${this.escape(run.project)}</strong></div>
						<div class="slow-ai-tools__row"><span>${__("Status")}</span><strong>${this.escape(run.status)}</strong></div>
						<div class="slow-ai-tools__row"><span>${__("Provider Tasks")}</span><strong>${this.escape(provider.total || 0)}</strong></div>
						<div class="slow-ai-tools__row"><span>${__("Cost")}</span><strong>${this.money(cost.debits_usd, cost.currency)}</strong></div>
						<div class="slow-ai-tools__row"><span>${__("Outputs")}</span><strong>${this.escape(run.asset_count || 0)}</strong></div>
						<div class="slow-ai-tools__muted">${this.escape(run.created || run.queued_at || "")}</div>
						<div class="slow-ai-tools__inline-actions">
							<button class="btn btn-xs btn-default" type="button" data-action="open-run-detail" data-run-id="${this.escape(run.workflow_run)}">${__("Open Detail")}</button>
							<a class="btn btn-xs btn-default" href="/app/slow-ai-tools">${__("Rerun Tool")}</a>
							${shareActions}
						</div>
					</article>`;
				})
				.join("")
		);
	}

	renderShareActions(run, canCreate = true) {
		if (run.status !== "SUCCEEDED") {
			return `<span class="slow-ai-tools__muted">${__("Share available after success")}</span>`;
		}
		const share = run.share || {};
		if (share.status === "ACTIVE" && share.share_token && share.share_url) {
			const url = this.absoluteShareUrl(share.share_url);
			return `<span class="slow-ai-tools__muted">${__("Share")}: ${this.escape(share.status)}</span>
				<button class="btn btn-xs btn-default" type="button" data-action="copy-share-link" data-share-url="${this.escape(url)}">${__("Copy Share Link")}</button>
				<button class="btn btn-xs btn-default" type="button" data-action="disable-run-share" data-share-token="${this.escape(share.share_token)}">${__("Disable Share")}</button>`;
		}
		if (!canCreate) {
			return `<span class="slow-ai-tools__muted">${__("Open detail to select outputs")}</span>`;
		}
		if (share.status) {
			return `<span class="slow-ai-tools__muted">${__("Share")}: ${this.escape(share.status)}</span>
				<button class="btn btn-xs btn-default" type="button" data-action="create-run-share" data-run-id="${this.escape(run.workflow_run)}">${__("Create Share Link")}</button>`;
		}
		return `<button class="btn btn-xs btn-default" type="button" data-action="create-run-share" data-run-id="${this.escape(run.workflow_run)}">${__("Create Share Link")}</button>`;
	}

	createRunShare(runId) {
		if (!runId) {
			return Promise.resolve();
		}
		const selectedAssets = this.selectedShareAssets(runId);
		if (!selectedAssets.length) {
			frappe.msgprint(__("Select at least one output asset to share."));
			return Promise.resolve();
		}
		return frappe
			.call("slow_ai.api.public_tools.create_run_share", {
				workflow_run: runId,
				selected_assets: selectedAssets,
			})
			.then((response) => {
				const share = response.message && response.message.share;
				if (share && share.share_url) {
					this.setStatus(__("Share link ready"));
					this.copyShareLink(this.absoluteShareUrl(share.share_url));
				}
				return this.loadMyRuns();
			});
	}

	disableRunShare(token) {
		if (!token) {
			return Promise.resolve();
		}
		return frappe
			.call("slow_ai.api.public_tools.disable_run_share", { share_token: token })
			.then(() => {
				this.setStatus(__("Share disabled"));
				return this.loadMyRuns();
			});
	}

	openRunDetail(runId) {
		if (!runId) {
			return Promise.resolve();
		}
		this.workflowRun = runId;
		this.$runDetail.html(`<div class="slow-ai-tools__empty">${__("Loading run detail")}</div>`);
		return frappe.call("slow_ai.api.public_tools.get_my_run", { workflow_run: runId }).then((response) => {
			const detail = response.message;
			this.renderRunStatus(detail.run || {});
			this.renderHistory(detail);
			this.renderRunDetail(detail);
			return this.renderOutputAssets(detail);
		});
	}

	renderRunDetail(detail) {
		const run = detail.run || {};
		const provider = detail.provider_summary || {};
		const cost = detail.cost_summary || {};
		const assetNames = this.assetNamesFromHistory(detail);
		const shareActions = this.renderShareActions(run, true);
		const shareSelection = this.renderShareAssetSelection(run, assetNames);
		this.$runDetail.html(`<div class="slow-ai-tools__run-card">
			<div class="slow-ai-tools__row"><span>${__("Run")}</span><strong>${this.escape(run.workflow_run)}</strong></div>
			<div class="slow-ai-tools__row"><span>${__("Title")}</span><strong>${this.escape(run.workflow_title || run.workflow || "")}</strong></div>
			<div class="slow-ai-tools__row"><span>${__("Status")}</span><strong>${this.escape(run.status)}</strong></div>
			<div class="slow-ai-tools__row"><span>${__("Queued")}</span><strong>${this.escape(run.queued_at || "-")}</strong></div>
			<div class="slow-ai-tools__row"><span>${__("Started")}</span><strong>${this.escape(run.started_at || "-")}</strong></div>
			<div class="slow-ai-tools__row"><span>${__("Completed")}</span><strong>${this.escape(run.completed_at || "-")}</strong></div>
			<div class="slow-ai-tools__row"><span>${__("Provider Tasks")}</span><strong>${this.escape(provider.total || 0)}</strong></div>
			<div class="slow-ai-tools__row"><span>${__("Cost")}</span><strong>${this.money(cost.debits_usd, cost.currency)}</strong></div>
			<div class="slow-ai-tools__row"><span>${__("Output Assets")}</span><strong>${this.escape(assetNames.length)}</strong></div>
			${shareSelection}
			<div class="slow-ai-tools__inline-actions">${shareActions}</div>
			${this.renderSafeErrors(detail)}
		</div>`);
	}

	renderShareAssetSelection(run, assetNames) {
		if (!run || run.status !== "SUCCEEDED") {
			return "";
		}
		if (!assetNames.length) {
			return `<div class="slow-ai-tools__empty">${__("No output assets are available to share")}</div>`;
		}
		const options = assetNames
			.map((assetName) => {
				return `<label class="slow-ai-tools__share-option">
					<input type="checkbox" data-share-asset="${this.escape(assetName)}" data-run-id="${this.escape(run.workflow_run)}" checked>
					<span>${this.escape(assetName)}</span>
				</label>`;
			})
			.join("");
		return `<div class="slow-ai-tools__share-assets" data-share-assets-run="${this.escape(run.workflow_run)}">
			<div class="slow-ai-tools__muted">${__("Select output assets to include in the share link")}</div>
			${options}
		</div>`;
	}

	assetNamesFromHistory(history) {
		const names = new Set();
		(history.assets || []).forEach((asset) => {
			if (asset.name) {
				names.add(asset.name);
			}
		});
		(history.node_runs || []).forEach((nodeRun) => {
			(nodeRun.asset_names || []).forEach((assetName) => names.add(assetName));
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
		const copy = url
			? `<button class="btn btn-xs btn-default" type="button" data-action="copy-asset-url" data-asset-url="${this.escape(url)}">${__("Copy URL")}</button>`
			: "";
		return `<article class="slow-ai-tools__asset-card" data-asset-name="${this.escape(asset.name)}">
			<div class="slow-ai-tools__asset-preview">${preview}</div>
			<div>
				<h4>${this.escape(asset.name)}</h4>
				<div class="slow-ai-tools__muted">${this.escape(asset.asset_type || "")} · ${this.escape(asset.mime_type || "")}</div>
				<div class="slow-ai-tools__muted">${__("Source Run")}: ${this.escape(asset.source_workflow_run || "-")}</div>
				<div class="slow-ai-tools__inline-actions">${open}${copy}</div>
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

	selectedShareAssets(runId) {
		const selector = `[data-share-assets-run="${this.escapeSelector(runId)}"] [data-share-asset]:checked`;
		return this.$runDetail
			.find(selector)
			.toArray()
			.map((element) => $(element).attr("data-share-asset"))
			.filter((assetName) => assetName);
	}

	copyAssetUrl(url) {
		if (!url) {
			return Promise.resolve();
		}
		if (navigator.clipboard && navigator.clipboard.writeText) {
			return navigator.clipboard.writeText(url).then(() => this.setStatus(__("Asset URL copied")));
		}
		window.prompt(__("Copy asset URL"), url);
		return Promise.resolve();
	}

	copyShareLink(url) {
		if (!url) {
			return Promise.resolve();
		}
		if (navigator.clipboard && navigator.clipboard.writeText) {
			return navigator.clipboard.writeText(url).then(() => this.setStatus(__("Share link copied")));
		}
		window.prompt(__("Copy share link"), url);
		return Promise.resolve();
	}

	absoluteShareUrl(path) {
		if (!path) {
			return "";
		}
		if (/^https?:\/\//i.test(path)) {
			return path;
		}
		return `${window.location.origin}${path}`;
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
