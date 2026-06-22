frappe.pages["slow-ai-admin"].on_page_load = function (wrapper) {
	const admin = new SlowAiAdminPage(wrapper);
	$(wrapper).data("slow-ai-admin", admin);
};

frappe.pages["slow-ai-admin"].on_page_show = function (wrapper) {
	const admin = $(wrapper).data("slow-ai-admin");
	if (admin && admin.loadedOnce) {
		admin.refresh();
	}
};

class SlowAiAdminPage {
	constructor(wrapper) {
		this.wrapper = wrapper;
		this.page = frappe.ui.make_app_page({
			parent: wrapper,
			title: __("Slow AI Admin"),
			single_column: true,
		});
		this.loadedOnce = false;
		this.makeBody();
		this.bindEvents();
		this.renderInitialState();
		this.refresh();
	}

	makeBody() {
		this.page.main.empty();
		$(frappe.render_template("slow_ai_admin")).appendTo(this.page.main);
		this.$root = this.page.main.find("[data-page='slow-ai-admin']");
		this.$controls = this.$root.find("[data-role='admin-controls']");
		this.$status = this.$root.find("[data-role='admin-status']");
		this.$unavailable = this.$root.find("[data-role='admin-unavailable']");
		this.$content = this.$root.find("[data-role='admin-content']");
		this.$overview = this.$root.find("[data-role='overview-metrics']");
		this.$runHealth = this.$root.find("[data-role='run-health']");
		this.$providerHealth = this.$root.find("[data-role='provider-job-health']");
		this.$billingHealth = this.$root.find("[data-role='billing-health']");
		this.$runFilter = this.$root.find("[data-filter='run-status']");
		this.$providerFilter = this.$root.find("[data-filter='provider-status']");
	}

	bindEvents() {
		this.$root.on("click", "[data-action='refresh-admin-health']", () => this.refresh());
		this.$root.on("change", "[data-filter='run-status']", () => this.loadRunHealth());
		this.$root.on("change", "[data-filter='provider-status']", () => this.loadProviderHealth());
	}

	renderInitialState() {
		this.$controls.addClass("hidden");
		this.$content.addClass("hidden");
		this.$unavailable.addClass("hidden");
		this.$status.removeClass("hidden").text(__("Loading system health"));
		this.renderLoading(this.$overview);
		this.renderLoading(this.$runHealth);
		this.renderLoading(this.$providerHealth);
		this.renderLoading(this.$billingHealth);
	}

	refresh() {
		this.renderInitialState();
		return this.loadOverview()
			.then(() => {
				this.loadedOnce = true;
				this.$controls.removeClass("hidden");
				this.$content.removeClass("hidden");
				this.$status.text(__("System health loaded"));
				return Promise.allSettled([this.loadRunHealth(), this.loadProviderHealth(), this.loadBillingHealth()]);
			})
			.catch(() => {
				this.loadedOnce = false;
				this.$controls.addClass("hidden");
				this.$content.addClass("hidden");
				this.$status.addClass("hidden");
				this.$unavailable.removeClass("hidden").text(__("System health unavailable"));
			});
	}

	loadOverview() {
		this.renderLoading(this.$overview);
		return frappe.call("slow_ai.api.admin.get_system_overview").then((response) => {
			this.renderOverview(response.message || {});
		});
	}

	loadRunHealth() {
		this.renderLoading(this.$runHealth);
		return frappe
			.call("slow_ai.api.admin.list_run_health", {
				status: this.$runFilter.val() || "ALL",
				limit: 25,
			})
			.then((response) => {
				const rows = (response.message && response.message.runs) || [];
				this.renderRows(this.$runHealth, rows, this.runRow.bind(this), __("No workflow runs found"));
			})
			.catch(() => {
				this.renderSectionError(this.$runHealth, __("Run health unavailable"));
			});
	}

	loadProviderHealth() {
		this.renderLoading(this.$providerHealth);
		return frappe
			.call("slow_ai.api.admin.list_provider_job_health", {
				status: this.$providerFilter.val() || "ALL",
				limit: 25,
			})
			.then((response) => {
				const rows = (response.message && response.message.provider_jobs) || [];
				this.renderRows(this.$providerHealth, rows, this.providerRow.bind(this), __("No provider jobs found"));
			})
			.catch(() => {
				this.renderSectionError(this.$providerHealth, __("Provider job health unavailable"));
			});
	}

	loadBillingHealth() {
		this.renderLoading(this.$billingHealth);
		return frappe
			.call("slow_ai.api.admin.list_billing_health", { limit: 25 })
			.then((response) => {
				const rows = (response.message && response.message.projects) || [];
				this.renderRows(this.$billingHealth, rows, this.billingRow.bind(this), __("No project billing rows found"));
			})
			.catch(() => {
				this.renderSectionError(this.$billingHealth, __("Billing health unavailable"));
			});
	}

	renderOverview(payload) {
		const workflowRuns = payload.workflow_runs || {};
		const providerJobs = payload.provider_jobs || {};
		const billing = payload.billing || {};
		const metrics = [
			["Active Runs", workflowRuns.active_count || 0],
			["Stale Runs", workflowRuns.stale_waiting_provider_count || 0],
			["Active Provider Jobs", providerJobs.active_count || 0],
			["Stale Provider Jobs", providerJobs.stale_waiting_provider_count || 0],
			["Reserved USD", billing.reserved_usd || "0"],
			["Available USD", billing.available_balance_usd || "0"],
			["Run Status Counts", this.statusSummary(workflowRuns.by_status)],
			["Provider Job Counts", this.statusSummary(providerJobs.by_status)],
			["Model Status Counts", this.statusSummary((payload.models || {}).by_status)],
			["Provider Account Counts", this.statusSummary((payload["provider_" + "accounts"] || {}).by_status)],
			["Share Status Counts", this.statusSummary((payload.shares || {}).by_status)],
		];
		this.$overview.html(metrics.map(([label, value]) => this.metric(label, value)).join(""));
	}

	renderRows($target, rows, renderer, emptyMessage) {
		if (!rows.length) {
			this.renderEmpty($target, emptyMessage);
			return;
		}
		$target.html(`<div class="slow-ai-admin__list">${rows.map((row) => renderer(row)).join("")}</div>`);
	}

	runRow(row) {
		return this.row(
			row.workflow_run,
			row.status,
			`Project ${row.project || "unknown"}`,
			`${row.node_run_count || 0} nodes / ${row.provider_job_count || 0} provider jobs`,
			row.modified
		);
	}

	providerRow(row) {
		return this.row(
			row.provider_job,
			row.status,
			`${row.provider || "provider"} / ${row.model || "model"}`,
			`${row.poll_attempts || 0} polls / ${row.debit_cost_usd || "0"} USD`,
			row.modified
		);
	}

	billingRow(row) {
		return this.row(
			row.project,
			row.status,
			row.project_name || row.project,
			`${row.balance_usd || "0"} USD balance`,
			row.latest_ledger_at
		);
	}

	row(title, status, meta, detail, timestamp) {
		return `
			<div class="slow-ai-admin__row">
				<div>
					<div class="slow-ai-admin__row-title">${this.escape(title || "")}</div>
					<div class="slow-ai-admin__row-meta">${this.escape(meta || "")}</div>
				</div>
				<div><span class="slow-ai-admin__status-pill">${this.escape(status || "UNKNOWN")}</span></div>
				<div class="slow-ai-admin__row-meta">${this.escape(detail || "")}</div>
				<div class="slow-ai-admin__row-meta">${this.formatTimestamp(timestamp)}</div>
			</div>
		`;
	}

	metric(label, value) {
		return `
			<div class="slow-ai-admin__metric">
				<div class="slow-ai-admin__metric-label">${this.escape(label)}</div>
				<div class="slow-ai-admin__metric-value">${this.escape(value)}</div>
			</div>
		`;
	}

	statusSummary(counts) {
		const entries = Object.entries(counts || {});
		if (!entries.length) {
			return "0";
		}
		return entries.map(([status, count]) => `${status}: ${count}`).join(" / ");
	}

	renderLoading($target) {
		$target.html(`<div class="slow-ai-admin__loading">${this.escape(__("Loading"))}</div>`);
	}

	renderEmpty($target, message) {
		$target.html(`<div class="slow-ai-admin__empty">${this.escape(message)}</div>`);
	}

	renderSectionError($target, message) {
		$target.html(`<div class="slow-ai-admin__error">${this.escape(message)}</div>`);
	}

	formatTimestamp(value) {
		const date = value instanceof Date ? value : new Date(value);
		if (!value || Number.isNaN(date.getTime())) {
			return "";
		}
		return date.toLocaleString();
	}

	escape(value) {
		return String(value == null ? "" : value)
			.replace(/&/g, "&amp;")
			.replace(/</g, "&lt;")
			.replace(/>/g, "&gt;")
			.replace(/"/g, "&quot;")
			.replace(/'/g, "&#39;");
	}
}
