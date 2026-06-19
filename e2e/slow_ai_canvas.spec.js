const { execFileSync } = require("child_process");
const { expect, test } = require("@playwright/test");

const API = {
	objectInfo: "slow_ai.api.nodes.get_object_info",
	saveWorkflow: "slow_ai.api.workflows.save_workflow",
	startRun: "slow_ai.api.runs.start_run",
	runStatus: "slow_ai.api.runs.get_run_status",
	history: "slow_ai.api.runs.get_history",
	assetUpload: "slow_ai.api.assets.upload",
	assetView: "slow_ai.api.assets.view",
	listTemplates: "slow_ai.api.templates.list_templates",
	getTemplate: "slow_ai.api.templates.get_template",
	createWorkflowFromTemplate: "slow_ai.api.templates.create_workflow_from_template",
	modelMetadata: "slow_ai.api.models.get_model_metadata",
	listProviderAccounts: "slow_ai.api.provider_accounts.list_accounts",
	getProviderAccount: "slow_ai.api.provider_accounts.get_account",
	createProviderAccount: "slow_ai.api.provider_accounts.create_account",
	setDefaultProviderAccount: "slow_ai.api.provider_accounts.set_default",
	disableProviderAccount: "slow_ai.api.provider_accounts.disable_account",
};

let fixtures;

test.beforeAll(async ({}, testInfo) => {
	const benchCwd = testInfo.config.metadata.benchCwd;
	const site = testInfo.config.metadata.site;
	const stdout = execFileSync(
		"bench",
		["--site", site, "execute", "slow_ai.tests.e2e.fixtures.setup_canvas_e2e"],
		{ cwd: benchCwd, encoding: "utf8", stdio: ["ignore", "pipe", "inherit"] }
	);
	const payload = stdout.trim().split(/\r?\n/).filter(Boolean).pop();
	fixtures = JSON.parse(payload);
});

function apiPredicate(method) {
	return (response) =>
		response.request().method() === "POST" &&
		response.url().includes(`/api/method/${method}`) &&
		response.status() === 200;
}

async function apiJson(response) {
	return response.json();
}

async function canvas(page) {
	return page.evaluateHandle(() => {
		const wrappers = window.$(".page-container, .page-wrapper").toArray();
		for (const wrapper of wrappers) {
			const data = window.$(wrapper).data();
			const instance = data.slowAiCanvas || data["slow-ai-canvas"];
			if (instance) {
				return instance;
			}
		}
		return null;
	});
}

async function setCanvasField(page, fieldname, value) {
	const control = page.locator(`[data-role="draft-controls"] .frappe-control[data-fieldname="${fieldname}"]`);
	await expect(control).toBeVisible();
	await control.locator("input").first().fill(value);
	await page.evaluate(
		({ fieldname: name, value: fieldValue }) => {
			const wrappers = window.$(".page-container, .page-wrapper").toArray();
			let instance = null;
			for (const wrapper of wrappers) {
				const data = window.$(wrapper).data();
				instance = data.slowAiCanvas || data["slow-ai-canvas"];
				if (instance) {
					break;
				}
			}
			instance[`${name}Field`].set_value(fieldValue);
		},
		{ fieldname, value }
	);
}

async function clickCanvasButton(page, label) {
	const visibleButton = page.locator("button:visible, a:visible").filter({ hasText: label }).first();
	if ((await visibleButton.count()) > 0) {
		await visibleButton.click();
		return;
	}
	const workflowGroup = page.locator(".inner-group-button").filter({ hasText: "Workflow" }).first();
	await workflowGroup.locator("button").first().click();
	await page.locator(".dropdown-menu.show a, .dropdown-menu a:visible").filter({ hasText: label }).first().click();
}

async function closeVisibleModal(page) {
	const modal = page.locator(".modal.show:visible").last();
	await expect(modal).toBeVisible();
	const footerButton = modal.locator(".modal-footer button:visible").last();
	if ((await footerButton.count()) > 0) {
		await footerButton.click();
	} else {
		await modal.locator("button:visible").last().click();
	}
	await expect(modal).toBeHidden();
}

test("Slow AI canvas and Tool Mode use real backend APIs only", async ({ page }) => {
	const providerRequests = [];
	page.on("request", (request) => {
		const url = request.url();
		if (url.includes("api.wavespeed.ai") || url.includes("wavespeed.ai/api")) {
			providerRequests.push(url);
		}
	});
	const objectInfoPromise = page.waitForResponse(apiPredicate(API.objectInfo));
	const templateListPromise = page.waitForResponse(apiPredicate(API.listTemplates));
	const initialProviderAccountsPromise = page.waitForResponse(apiPredicate(API.listProviderAccounts));

	await page.request.post("/api/method/login", {
		form: {
			usr: fixtures.user,
			pwd: fixtures.password,
		},
	});
	await page.goto("/app/slow-ai-canvas");
	await expect.poll(() => page.evaluate(() => window.frappe && window.frappe.session.user)).toBe(fixtures.user);

	const objectInfo = await apiJson(await objectInfoPromise);
	expect(objectInfo.message.nodes.text_prompt.category).toBe("input");
	const templates = await apiJson(await templateListPromise);
	expect(Array.isArray(templates.message.templates)).toBe(true);
	const initialProviderAccounts = await apiJson(await initialProviderAccountsPromise);
	expect(Array.isArray(initialProviderAccounts.message.accounts)).toBe(true);
	await expect(page.locator("[data-role='node-palette']")).toContainText("Text Prompt");
	await expect(page.locator("[data-role='template-library']")).toContainText("Refresh Templates");
	await expect(page.locator("[data-role='provider-accounts']")).toContainText("Create Provider Account");

	await setCanvasField(page, "project", fixtures.project);
	await setCanvasField(page, "title", fixtures.canvas_title);
	await page.locator("[data-role='provider-accounts'] [data-provider-account-field='provider']").fill(fixtures.provider_account_provider);
	await page.locator("[data-role='provider-accounts'] [data-provider-account-field='account_label']").fill(fixtures.provider_account_label);
	await page.locator("[data-role='provider-accounts'] [data-provider-account-field='api_key']").fill(fixtures.provider_account_secret);
	await page.locator("[data-role='provider-accounts'] [data-provider-account-field='project']").fill(fixtures.project);
	const createProviderAccountResponse = page.waitForResponse(apiPredicate(API.createProviderAccount));
	const reloadProviderAccountsResponse = page.waitForResponse(apiPredicate(API.listProviderAccounts));
	await page.locator("[data-role='provider-accounts']").getByRole("button", { name: "Create Account" }).click();
	const createdProviderAccount = await apiJson(await createProviderAccountResponse);
	await reloadProviderAccountsResponse;
	const providerAccountName = createdProviderAccount.message.account.name;
	expect(createdProviderAccount.message.account.provider).toBe(fixtures.provider_account_provider);
	expect(JSON.stringify(createdProviderAccount)).not.toContain(fixtures.provider_account_secret);
	await expect(page.locator("[data-role='provider-accounts']")).toContainText(fixtures.provider_account_label);
	await expect(page.locator("[data-role='provider-accounts'] [data-provider-account-field='api_key']")).toHaveValue("");

	const getProviderAccountResponse = page.waitForResponse(apiPredicate(API.getProviderAccount));
	await page.locator(`[data-provider-account-name="${providerAccountName}"]`).getByRole("button", { name: "View" }).click();
	const fetchedProviderAccount = await apiJson(await getProviderAccountResponse);
	expect(fetchedProviderAccount.message.account.name).toBe(providerAccountName);
	expect(JSON.stringify(fetchedProviderAccount)).not.toContain(fixtures.provider_account_secret);
	await closeVisibleModal(page);

	const defaultProviderAccountResponse = page.waitForResponse(apiPredicate(API.setDefaultProviderAccount));
	await page.locator(`[data-provider-account-name="${providerAccountName}"]`).getByRole("button", { name: "Set Default" }).click();
	const defaultProviderAccount = await apiJson(await defaultProviderAccountResponse);
	expect(Boolean(defaultProviderAccount.message.account.is_default)).toBe(true);

	const disableProviderAccountResponse = page.waitForResponse(apiPredicate(API.disableProviderAccount));
	await page.locator(`[data-provider-account-name="${providerAccountName}"]`).getByRole("button", { name: "Disable" }).click();
	const disabledProviderAccount = await apiJson(await disableProviderAccountResponse);
	expect(disabledProviderAccount.message.account.status).toBe("DISABLED");
	await expect(page.locator(`[data-provider-account-name="${providerAccountName}"]`)).toContainText("DISABLED");

	await page
		.locator("[data-role='node-palette'] [data-palette-node-type='text_prompt']")
		.first()
		.getByRole("button", { name: "Add Node" })
		.click();
	const addedNodes = page.locator("[data-role='nodes'] > .slow-ai-canvas__node[data-node-id^='text_prompt_']");
	await expect(addedNodes.first()).toBeVisible();
	const addedNode = addedNodes.last();
	await expect(addedNode).toContainText("Text Prompt");
	const addedNodeId = await addedNode.getAttribute("data-node-id");
	const initialPosition = await page.evaluate((nodeId) => {
		const instance = window.$(".page-container, .page-wrapper")
			.toArray()
			.map((wrapper) => {
				const data = window.$(wrapper).data();
				return data.slowAiCanvas || data["slow-ai-canvas"];
			})
			.find(Boolean);
		const node = instance.nodes.find((row) => row.id === nodeId);
		return node.position;
	}, addedNodeId);
	const handle = addedNode.locator("[data-node-drag-handle]");
	const handleBox = await handle.boundingBox();
	await page.mouse.move(handleBox.x + handleBox.width / 2, handleBox.y + handleBox.height / 2);
	await page.mouse.down();
	await page.mouse.move(handleBox.x + handleBox.width / 2 + 84, handleBox.y + handleBox.height / 2 + 42, { steps: 8 });
	await page.mouse.up();
	await expect(page.locator("[data-role='status']")).toContainText(`Moved node ${addedNodeId}`);
	const movedPosition = await page.evaluate((nodeId) => {
		const instance = window.$(".page-container, .page-wrapper")
			.toArray()
			.map((wrapper) => {
				const data = window.$(wrapper).data();
				return data.slowAiCanvas || data["slow-ai-canvas"];
			})
			.find(Boolean);
		const node = instance.nodes.find((row) => row.id === nodeId);
		return node.position;
	}, addedNodeId);
	expect(movedPosition.x).toBeGreaterThan(initialPosition.x);
	expect(movedPosition.y).toBeGreaterThan(initialPosition.y);
	await addedNode.click();
	await page.locator("[data-role='node-editor'] [data-config-field='text']").fill("Browser edited prompt");

	await page.locator("[data-role='edges'] [data-action='delete-visual-edge'][data-edge-id='edge_1']").click({ force: true });
	await expect(page.locator("[data-role='status']")).toContainText("Deleted edge");
	await page.locator("[data-node-id='prompt_1'] [data-port-direction='output'][data-port-name='text']").click();
	await expect(page.locator("[data-role='status']")).toContainText("Select a compatible input port");
	await page.locator("[data-node-id='image_1'] [data-port-direction='input'][data-port-name='prompt']").click();
	await expect(page.locator("[data-role='status']")).toContainText("Added edge");

	const saveResponse = page.waitForResponse(apiPredicate(API.saveWorkflow));
	await clickCanvasButton(page, "Save Draft");
	const saved = await apiJson(await saveResponse);
	expect(saved.message.name).toMatch(/^AI-WORKFLOW-/);
	expect(saved.message.layout.nodes.length).toBeGreaterThan(0);
	const savedMovedNode = saved.message.layout.nodes.find((row) => row.id === addedNodeId);
	expect(savedMovedNode.x).toBe(movedPosition.x);
	expect(savedMovedNode.y).toBe(movedPosition.y);

	const modelMetadataResponse = page.waitForResponse(apiPredicate(API.modelMetadata));
	await clickCanvasButton(page, "Start Run");
	await modelMetadataResponse;
	const modal = page.locator(".modal:visible");
	await expect(modal).toContainText("This workflow may call an external provider and spend credits.");
	await expect(modal).toContainText("wavespeed");
	await expect(modal).toContainText("wavespeed-ai/flux-dev");
	await modal.locator(".btn-secondary").first().click();
	await expect(page.locator("[data-role='status']")).toContainText("Run cancelled");

	await expect(page.locator("[data-role='template-library']")).toContainText(fixtures.tool_template_label);
	const templatePreviewResponse = page.waitForResponse(apiPredicate(API.getTemplate));
	await page.locator(`[data-template-name="${fixtures.tool_template}"]`).first().getByRole("button", { name: "Load Template Preview" }).click();
	const templatePreview = await apiJson(await templatePreviewResponse);
	expect(templatePreview.message.name).toBe(fixtures.tool_template);
	await expect(page.locator("[data-role='template-preview']")).toContainText(fixtures.tool_template_label);

	const toolTemplateResponse = page.waitForResponse(apiPredicate(API.getTemplate));
	await page.locator("[data-tool-template]").selectOption(fixtures.tool_template);
	const toolTemplate = await apiJson(await toolTemplateResponse);
	expect(toolTemplate.message.name).toBe(fixtures.tool_template);
	await expect(page.locator("[data-role='tool-mode']")).toContainText(fixtures.tool_template_label);
	await page.locator("[data-tool-node-id='prompt_1'][data-tool-config-field='text']").fill(fixtures.tool_prompt);

	const createToolWorkflowResponse = page.waitForResponse(apiPredicate(API.createWorkflowFromTemplate));
	const saveToolWorkflowResponse = page.waitForResponse(apiPredicate(API.saveWorkflow));
	const startToolRunResponse = page.waitForResponse(apiPredicate(API.startRun));
	const statusToolResponse = page.waitForResponse(apiPredicate(API.runStatus));
	const historyToolResponse = page.waitForResponse(apiPredicate(API.history));
	await page.locator("[data-role='tool-mode']").getByRole("button", { name: "Run Tool" }).click();
	await createToolWorkflowResponse;
	const savedTool = await apiJson(await saveToolWorkflowResponse);
	const promptNode = savedTool.message.nodes.find((node) => node.id === "prompt_1");
	expect(promptNode.config.text).toBe(fixtures.tool_prompt);
	await startToolRunResponse;
	const statusPayload = await apiJson(await statusToolResponse);
	expect(statusPayload.message.workflow_run).toMatch(/^AI-WORKFLOW-RUN-/);
	const historyPayload = await apiJson(await historyToolResponse);
	expect(historyPayload.message.run.workflow_run).toMatch(/^AI-WORKFLOW-RUN-/);
	await expect(page.locator("[data-role='run-summary']")).toContainText("Workflow Status");
	await expect(page.locator("[data-role='history']")).toContainText("Run");

	const uploadTemplateResponse = page.waitForResponse(apiPredicate(API.getTemplate));
	await page.locator("[data-tool-template]").selectOption(fixtures.upload_template);
	const uploadTemplate = await apiJson(await uploadTemplateResponse);
	expect(uploadTemplate.message.name).toBe(fixtures.upload_template);
	await page.locator("[data-tool-node-id='asset_1'][data-tool-config-field='asset']").fill(fixtures.selected_asset);
	const selectedAssetViewResponse = page.waitForResponse(apiPredicate(API.assetView));
	await page.locator("[data-role='tool-mode']").getByRole("button", { name: "Preview Selected Asset" }).click();
	const selectedAsset = await apiJson(await selectedAssetViewResponse);
	expect(selectedAsset.message.name).toBe(fixtures.selected_asset);
	await expect(page.locator(`[data-tool-preview-asset="${fixtures.selected_asset}"]`)).toContainText(fixtures.selected_asset);

	await page.locator("[data-tool-node-id='asset_1'][data-tool-upload-url]").fill(fixtures.upload_url);
	await page.locator("[data-tool-node-id='asset_1'][data-tool-upload-mime]").fill("image/png");
	const uploadResponse = page.waitForResponse(apiPredicate(API.assetUpload));
	await page.locator("[data-role='tool-mode']").getByRole("button", { name: "Create AI Asset" }).click();
	const uploaded = await apiJson(await uploadResponse);
	expect(uploaded.message.url).toBe(fixtures.upload_url);
	fixtures.created_asset = uploaded.message.name;

	const createUploadWorkflowResponse = page.waitForResponse(apiPredicate(API.createWorkflowFromTemplate));
	const saveUploadWorkflowResponse = page.waitForResponse(apiPredicate(API.saveWorkflow));
	const startUploadRunResponse = page.waitForResponse(apiPredicate(API.startRun));
	await page.locator("[data-role='tool-mode']").getByRole("button", { name: "Run Tool" }).click();
	await createUploadWorkflowResponse;
	const savedUpload = await apiJson(await saveUploadWorkflowResponse);
	const assetNode = savedUpload.message.nodes.find((node) => node.id === "asset_1");
	expect(assetNode.config.asset).toBe(fixtures.created_asset);
	expect(assetNode.config.asset_type).toBe("IMAGE");
	await startUploadRunResponse;

	await page.evaluate(async (workflowRun) => {
		const wrappers = window.$(".page-container, .page-wrapper").toArray();
		let instance = null;
		for (const wrapper of wrappers) {
			const data = window.$(wrapper).data();
			instance = data.slowAiCanvas || data["slow-ai-canvas"];
			if (instance) {
				break;
			}
		}
		instance.workflowRun = workflowRun;
		await instance.refreshRun();
	}, fixtures.asset_workflow_run);
	await expect(page.locator("[data-role='asset-output'] .slow-ai-canvas__asset-card")).toContainText(fixtures.history_asset);
	await expect(page.locator("[data-role='asset-output']")).toContainText("Open Asset");
	await expect(page.locator("[data-role='asset-output']")).toContainText("Refresh Asset");

	const pageSource = await page.locator("html").innerHTML();
	expect(pageSource).not.toContain("WAVESPEED_API_KEY");
	expect(pageSource).not.toContain("api_key_secret");
	expect(pageSource).not.toContain(fixtures.provider_account_secret);
	expect(pageSource).not.toContain("api.wavespeed.ai");
	expect(pageSource).not.toContain("Authorization: Bearer");
	expect(providerRequests).toEqual([]);

	const instance = await canvas(page);
	expect(await instance.evaluate((value) => Boolean(value.workflowRun))).toBe(true);
});
