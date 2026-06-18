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
		this.nodeRunsByNodeId = {};
		this.pollTimer = null;
		this.nodes = this.defaultNodes();
		this.edges = this.defaultEdges();
		this.layout = { nodes: this.nodes.map((node) => ({ id: node.id, ...node.position })) };
		this.makeControls();
		this.makeBody();
		this.bindRealtime();
		this.render();
	}

	makeControls() {
		this.projectField = this.page.add_field({
			label: __("Project"),
			fieldname: "project",
			fieldtype: "Link",
			options: "AI Project",
			reqd: 1,
		});
		this.workflowField = this.page.add_field({
			label: __("Workflow"),
			fieldname: "workflow",
			fieldtype: "Link",
			options: "AI Workflow",
			change: () => this.loadWorkflow(),
		});
		this.titleField = this.page.add_field({
			label: __("Title"),
			fieldname: "title",
			fieldtype: "Data",
			default: "Untitled AI Workflow",
		});
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
		this.$status = this.$root.find("[data-role='status']");
		this.$run = this.$root.find("[data-role='run']");
		this.$palette = this.$root.find("[data-role='node-palette']");
		this.$stage = this.$root.find("[data-role='stage']");
		this.$edges = this.$root.find("[data-role='edges']");
		this.$nodes = this.$root.find("[data-role='nodes']");
		this.$queue = this.$root.find("[data-role='queue-summary']");
		this.$summary = this.$root.find("[data-role='run-summary']");
		this.$history = this.$root.find("[data-role='history']");
		this.$assets = this.$root.find("[data-role='asset-output']");
		this.$palette.on("click", "[data-action='add-node']", (event) => {
			const nodeType = $(event.currentTarget).attr("data-node-type");
			this.addNodeFromMetadata(nodeType);
		});
	}

	show() {
		this.loadObjectInfo();
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
			this.workflowRun = null;
			this.nodeRunsByNodeId = {};
			this.setStatus(__("Loaded {0}", [draft.name]));
			this.render();
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
		this.layout = { nodes: this.nodes.map((node) => ({ id: node.id, ...node.position })) };
		this.nodeRunsByNodeId = {};
		this.setStatus(__("New draft"));
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

	renderNodes() {
		const html = this.nodes
			.map((node) => {
				const nodeRun = this.nodeRunsByNodeId[node.id] || {};
				const status = nodeRun.status || "DRAFT";
				const position = node.position || { x: 0, y: 0 };
				return `<div class="slow-ai-canvas__node" data-node-id="${this.escape(node.id)}" data-node-status="${this.escape(status)}" style="left: ${position.x}px; top: ${position.y}px;">
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

	renderRunSummary(status) {
		const nodeCounts = (status.node_runs || []).reduce((counts, nodeRun) => {
			counts[nodeRun.status] = (counts[nodeRun.status] || 0) + 1;
			return counts;
		}, {});
		const counts = Object.keys(nodeCounts)
			.sort()
			.map((key) => `${this.escape(key)}: ${nodeCounts[key]}`)
			.join("<br>");
		this.$summary.html(`
			<div class="slow-ai-canvas__metric">${__("Workflow")}: ${this.escape(status.workflow)}</div>
			<div class="slow-ai-canvas__metric">${__("Status")}: ${this.escape(status.status)}</div>
			<div class="slow-ai-canvas__metric">${counts}</div>
		`);
	}

	renderHistory(history) {
		const assets = history.assets || [];
		const ledger = history.ledger || [];
		const jobs = history.provider_jobs || [];
		this.$history.html(`
			<div class="slow-ai-canvas__history-item">${__("Assets")}: ${assets.length}</div>
			<div class="slow-ai-canvas__history-item">${__("Provider Jobs")}: ${jobs.length}</div>
			<div class="slow-ai-canvas__history-item">${__("Ledger Entries")}: ${ledger.length}</div>
		`);
		this.renderAssetOutputs(assets);
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
			const html = viewedAssets
				.map((asset) => {
					const href = asset.file || asset.url || "";
					const link = href
						? `<a class="slow-ai-canvas__asset-link" href="${this.escape(href)}" target="_blank" rel="noopener">${this.escape(href)}</a>`
						: this.escape(asset.name);
					return `<div class="slow-ai-canvas__asset-item">
						<div>${this.escape(asset.asset_type)} · ${this.escape(asset.name)}</div>
						<div>${link}</div>
					</div>`;
				})
				.join("");
			this.$assets.html(html);
		});
	}

	setStatus(message) {
		this.$status.text(message);
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
