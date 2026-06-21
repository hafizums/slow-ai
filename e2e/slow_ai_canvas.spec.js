const { execFileSync } = require("child_process");
const { expect, test } = require("@playwright/test");

const API = {
	objectInfo: "slow_ai.api.nodes.get_object_info",
	saveWorkflow: "slow_ai.api.workflows.save_workflow",
	startRun: "slow_ai.api.runs.start_run",
	runStatus: "slow_ai.api.runs.get_run_status",
	history: "slow_ai.api.runs.get_history",
	runTimeline: "slow_ai.api.runs.get_run_timeline",
	assetUpload: "slow_ai.api.assets.upload",
	assetView: "slow_ai.api.assets.view",
	listTemplates: "slow_ai.api.templates.list_templates",
	getTemplate: "slow_ai.api.templates.get_template",
	saveTemplate: "slow_ai.api.templates.save_template",
	createWorkflowFromTemplate: "slow_ai.api.templates.create_workflow_from_template",
	submitTemplateReview: "slow_ai.api.templates.submit_template_for_review",
	approveTemplate: "slow_ai.api.templates.approve_template",
	rejectTemplate: "slow_ai.api.templates.reject_template",
	archiveTemplate: "slow_ai.api.templates.archive_template",
	listTemplateVersions: "slow_ai.api.templates.list_template_versions",
	rollbackTemplateVersion: "slow_ai.api.templates.rollback_template_to_version",
	publicListTemplates: "slow_ai.api.public_tools.list_templates",
	publicGetTemplate: "slow_ai.api.public_tools.get_template",
	publicCreateWorkflowFromTemplate: "slow_ai.api.public_tools.create_workflow_from_template",
	publicPrepareWorkflowFromTemplate: "slow_ai.api.public_tools.prepare_workflow_from_template",
	publicPrepareRerunFromRun: "slow_ai.api.public_tools.prepare_rerun_from_run",
	publicUpdateRerunDraftValues: "slow_ai.api.public_tools.update_rerun_draft_values",
	publicListMyRuns: "slow_ai.api.public_tools.list_my_runs",
	publicGetMyRun: "slow_ai.api.public_tools.get_my_run",
	publicGetRunOutputGallery: "slow_ai.api.public_tools.get_run_output_gallery",
	publicCancelMyRun: "slow_ai.api.public_tools.cancel_my_run",
	publicArchiveMyRun: "slow_ai.api.public_tools.archive_my_run",
	publicCreateRunShare: "slow_ai.api.public_tools.create_run_share",
	publicDisableRunShare: "slow_ai.api.public_tools.disable_run_share",
	publicGetSharedRun: "slow_ai.api.public_tools.get_shared_run",
	modelMetadata: "slow_ai.api.models.get_model_metadata",
	billingBalance: "slow_ai.api.billing.get_balance",
	listProviderAccounts: "slow_ai.api.provider_accounts.list_accounts",
	getProviderAccount: "slow_ai.api.provider_accounts.get_account",
	createProviderAccount: "slow_ai.api.provider_accounts.create_account",
	setDefaultProviderAccount: "slow_ai.api.provider_accounts.set_default",
	disableProviderAccount: "slow_ai.api.provider_accounts.disable_account",
	listModels: "slow_ai.api.models.list_models",
	getModel: "slow_ai.api.models.get_model",
	updateModelStatus: "slow_ai.api.models.update_model_status",
	updateModelPricing: "slow_ai.api.models.update_model_pricing",
	listProjectMembers: "slow_ai.api.projects.list_members",
	addProjectMember: "slow_ai.api.projects.add_member",
	updateProjectMemberRole: "slow_ai.api.projects.update_member_role",
	disableProjectMember: "slow_ai.api.projects.disable_member",
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

function apiAnyStatusPredicate(method) {
	return (response) =>
		response.request().method() === "POST" && response.url().includes(`/api/method/${method}`);
}

async function apiJson(response) {
	return response.json();
}

async function callApi(page, method, args = {}) {
	const response = await page.request.post(`/api/method/${method}`, { form: args });
	expect(response.status()).toBe(200);
	const payload = await response.json();
	return payload.message;
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
		if (url.includes("api.wavespeed.ai") || url.includes("wavespeed.ai/api") || url.includes("api.replicate.com")) {
			providerRequests.push(url);
		}
	});
	const objectInfoPromise = page.waitForResponse(apiPredicate(API.objectInfo));
	const templateListPromise = page.waitForResponse(apiPredicate(API.listTemplates));
	const initialProviderAccountsPromise = page.waitForResponse(apiPredicate(API.listProviderAccounts));
	const initialModelsPromise = page.waitForResponse(apiPredicate(API.listModels));

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
	const initialModels = await apiJson(await initialModelsPromise);
	expect(Array.isArray(initialModels.message.models)).toBe(true);
	await expect(page.locator("[data-role='node-palette']")).toContainText("Text Prompt");
	await expect(page.locator("[data-role='template-library']")).toContainText("Refresh Templates");
	await expect(page.locator("[data-role='provider-accounts']")).toContainText("Create Provider Account");
	await expect(page.locator("[data-role='model-catalog']")).toContainText("Refresh Models");

	await setCanvasField(page, "project", fixtures.project);
	await setCanvasField(page, "title", fixtures.canvas_title);

	const filteredModelsResponse = page.waitForResponse(apiPredicate(API.listModels));
	await page.locator("[data-role='model-catalog'] [data-model-filter='provider']").evaluate(
		(element, provider) => {
			element.value = provider;
			element.dispatchEvent(new Event("change", { bubbles: true }));
		},
		fixtures.model_catalog_provider
	);
	const filteredModels = await apiJson(await filteredModelsResponse);
	expect(filteredModels.message.models.some((model) => model.name === fixtures.model_catalog_model)).toBe(true);
	await expect(page.locator("[data-role='model-catalog']")).toContainText(fixtures.model_catalog_label);
	await expect(page.locator("[data-role='model-catalog']")).toContainText(
		"Disabled model cannot pass run preflight."
	);
	await expect(page.locator("[data-role='model-catalog']")).toContainText(
		"Pricing unknown; strict preflight will reject this model."
	);
	const modelDetailResponse = page.waitForResponse(apiPredicate(API.getModel));
	await page
		.locator(`[data-model-name="${fixtures.model_catalog_model}"]`)
		.getByRole("button", { name: "Inspect Model" })
		.click();
	const modelDetail = await apiJson(await modelDetailResponse);
	expect(modelDetail.message.model.name).toBe(fixtures.model_catalog_model);
	expect(modelDetail.message.model.pricing_known).toBe(false);
	await expect(page.locator(`[data-model-detail="${fixtures.model_catalog_model}"]`)).toContainText(
		"Model Detail"
	);

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

	await expect(page.locator("[data-role='template-library']")).toContainText(fixtures.public_review_template_label);
	const reviewTemplateCard = page.locator(
		`.slow-ai-canvas__template-card[data-template-name="${fixtures.public_review_template}"]`
	);
	await expect(reviewTemplateCard).toContainText("DRAFT");
	const submitReviewResponse = page.waitForResponse(apiPredicate(API.submitTemplateReview));
	const reloadAfterSubmitReviewResponse = page.waitForResponse(apiPredicate(API.listTemplates));
	await reviewTemplateCard.getByRole("button", { name: "Submit Review" }).click();
	const submittedReview = await apiJson(await submitReviewResponse);
	await reloadAfterSubmitReviewResponse;
	expect(submittedReview.message.status).toBe("IN_REVIEW");
	await expect(reviewTemplateCard).toContainText("IN_REVIEW");
	const approveReviewResponse = page.waitForResponse(apiPredicate(API.approveTemplate));
	const reloadAfterApproveReviewResponse = page.waitForResponse(apiPredicate(API.listTemplates));
	await reviewTemplateCard.getByRole("button", { name: "Approve" }).click();
	const approveModal = page.locator(".modal.show:visible").last();
	await expect(approveModal).toBeVisible();
	await approveModal.locator("textarea").fill("Browser E2E review approved.");
	await approveModal.getByRole("button", { name: "Approve" }).click();
	const approvedReview = await apiJson(await approveReviewResponse);
	await reloadAfterApproveReviewResponse;
	expect(approvedReview.message.status).toBe("PUBLISHED");
	expect(approvedReview.message.published_version).toBeTruthy();
	await expect(reviewTemplateCard).toContainText("PUBLISHED");
	const publicReviewV1 = await callApi(page, API.publicGetTemplate, {
		template: fixtures.public_review_template,
	});
	const publicReviewV1Prompt = publicReviewV1.nodes.find((node) => node.id === "prompt_1").config.text;
	expect(publicReviewV1.template_version).toBe(approvedReview.message.published_version);
	expect(publicReviewV1.version_no).toBe(1);

	const editedReviewNodes = approvedReview.message.nodes.map((node) =>
		node.id === "prompt_1"
			? { ...node, config: { ...node.config, text: "Browser mutable draft prompt" } }
			: node
	);
	await callApi(page, API.saveTemplate, {
		template: fixtures.public_review_template,
		template_name: approvedReview.message.template_name,
		status: "DRAFT",
		category: approvedReview.message.category,
		description: approvedReview.message.description,
		nodes: JSON.stringify(editedReviewNodes),
		edges: JSON.stringify(approvedReview.message.edges),
		layout: JSON.stringify(approvedReview.message.layout),
		input_schema_json: JSON.stringify(approvedReview.message.input_schema),
	});
	const publicReviewStillV1 = await callApi(page, API.publicGetTemplate, {
		template: fixtures.public_review_template,
	});
	expect(publicReviewStillV1.template_version).toBe(publicReviewV1.template_version);
	expect(publicReviewStillV1.nodes.find((node) => node.id === "prompt_1").config.text).toBe(publicReviewV1Prompt);

	await callApi(page, API.submitTemplateReview, { template: fixtures.public_review_template });
	const approvedReviewV2 = await callApi(page, API.approveTemplate, {
		template: fixtures.public_review_template,
		review_notes: "Browser E2E version 2.",
	});
	const publicReviewV2 = await callApi(page, API.publicGetTemplate, {
		template: fixtures.public_review_template,
	});
	expect(publicReviewV2.template_version).toBe(approvedReviewV2.published_version);
	expect(publicReviewV2.version_no).toBe(2);
	expect(publicReviewV2.nodes.find((node) => node.id === "prompt_1").config.text).toBe(
		"Browser mutable draft prompt"
	);

	const reviewVersions = await callApi(page, API.listTemplateVersions, {
		template: fixtures.public_review_template,
	});
	expect(reviewVersions.versions.find((version) => version.name === publicReviewV1.template_version).status).toBe(
		"SUPERSEDED"
	);
	expect(reviewVersions.versions.find((version) => version.name === publicReviewV2.template_version).status).toBe(
		"ACTIVE"
	);
	const rollbackReview = await callApi(page, API.rollbackTemplateVersion, {
		template: fixtures.public_review_template,
		template_version: publicReviewV1.template_version,
		review_notes: "Browser E2E rollback to version 1.",
	});
	const publicReviewV3 = await callApi(page, API.publicGetTemplate, {
		template: fixtures.public_review_template,
	});
	expect(publicReviewV3.template_version).toBe(rollbackReview.published_version);
	expect(publicReviewV3.version_no).toBe(3);
	expect(publicReviewV3.nodes.find((node) => node.id === "prompt_1").config.text).toBe(publicReviewV1Prompt);

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

	const canvasTimelineResponse = page.waitForResponse(apiPredicate(API.runTimeline));
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
	const canvasTimeline = await apiJson(await canvasTimelineResponse);
	expect(canvasTimeline.message.events.some((event) => event.event_type === "RUN_QUEUED")).toBe(true);
	await expect(page.locator(`[data-role='asset-output'] .slow-ai-canvas__asset-card[data-asset-name="${fixtures.history_asset}"]`)).toContainText(fixtures.history_asset);
	await expect(page.locator("[data-role='run-timeline']")).toContainText("Run queued");
	await expect(page.locator("[data-role='run-timeline']")).toContainText("Asset created");
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

test("Slow AI public tool page runs published templates through backend APIs", async ({ page, browser }) => {
	const providerRequests = [];
	page.on("request", (request) => {
		const url = request.url();
		if (url.includes("api.wavespeed.ai") || url.includes("wavespeed.ai/api") || url.includes("api.replicate.com")) {
			providerRequests.push(url);
		}
	});

	await page.request.post("/api/method/login", {
		form: {
			usr: fixtures.public_tool_user,
			pwd: fixtures.public_tool_password,
		},
	});

	const templateListResponse = page.waitForResponse(apiPredicate(API.publicListTemplates));
	const initialRunsResponse = page.waitForResponse(apiPredicate(API.publicListMyRuns));
	await page.goto("/app/slow-ai-tools");
	await expect.poll(() => page.evaluate(() => window.frappe && window.frappe.session.user)).toBe(
		fixtures.public_tool_user
	);
	await expect(page.locator("[data-page='slow-ai-tools']")).toBeVisible();

	const templates = await apiJson(await templateListResponse);
	expect(templates.message.templates.some((template) => template.name === fixtures.public_tool_template)).toBe(true);
	expect(templates.message.templates.some((template) => template.name === fixtures.public_review_template)).toBe(true);
	expect(templates.message.templates.some((template) => template.name === fixtures.public_rejected_template)).toBe(false);
	expect(templates.message.templates.some((template) => template.name === fixtures.public_archived_template)).toBe(false);
	const initialRuns = await apiJson(await initialRunsResponse);
	expect(Array.isArray(initialRuns.message.runs)).toBe(true);
	await expect(page.locator("[data-role='template-list']")).toContainText(fixtures.public_tool_template_label);
	await expect(page.locator("[data-role='template-list']")).toContainText(fixtures.public_review_template_label);
	await expect(page.locator("[data-role='template-list']")).not.toContainText(fixtures.public_rejected_template_label);
	await expect(page.locator("[data-role='template-list']")).not.toContainText(fixtures.public_archived_template_label);

	await page.locator("[data-role='project']").fill(fixtures.public_tool_project);
	const balanceResponse = page.waitForResponse(apiPredicate(API.billingBalance));
	await page.locator("[data-action='refresh-balance']").click();
	const balance = await apiJson(await balanceResponse);
	expect(balance.message.project).toBe(fixtures.public_tool_project);
	await expect(page.locator("[data-role='balance']")).toContainText("Balance");

	const memberListResponse = page.waitForResponse(apiPredicate(API.listProjectMembers));
	await page.locator("[data-action='refresh-project-members']").click();
	const memberList = await apiJson(await memberListResponse);
	expect(Array.isArray(memberList.message.members)).toBe(true);

	await page.locator("[data-role='member-user']").fill(fixtures.public_tool_editor_user);
	await page.locator("[data-role='member-role']").selectOption("EDITOR");
	const addEditorResponse = page.waitForResponse(apiPredicate(API.addProjectMember));
	const reloadAfterEditorResponse = page.waitForResponse(apiPredicate(API.listProjectMembers));
	await page.locator("[data-action='add-project-member']").click();
	const addedEditor = await apiJson(await addEditorResponse);
	await reloadAfterEditorResponse;
	expect(addedEditor.message.member.role).toBe("EDITOR");
	await expect(page.locator("[data-role='project-members']")).toContainText(fixtures.public_tool_editor_user);

	await page.locator("[data-role='member-user']").fill(fixtures.public_tool_viewer_user);
	await page.locator("[data-role='member-role']").selectOption("VIEWER");
	const addViewerResponse = page.waitForResponse(apiPredicate(API.addProjectMember));
	const reloadAfterViewerResponse = page.waitForResponse(apiPredicate(API.listProjectMembers));
	await page.locator("[data-action='add-project-member']").click();
	const addedViewer = await apiJson(await addViewerResponse);
	await reloadAfterViewerResponse;
	expect(addedViewer.message.member.role).toBe("VIEWER");
	await expect(page.locator("[data-role='project-members']")).toContainText(fixtures.public_tool_viewer_user);

	const templateResponse = page.waitForResponse(apiPredicate(API.publicGetTemplate));
	await page
		.locator(`[data-template-name="${fixtures.public_tool_template}"]`)
		.getByRole("button", { name: "Select" })
		.click();
	const template = await apiJson(await templateResponse);
	expect(template.message.name).toBe(fixtures.public_tool_template);
	await expect(page.locator("[data-role='template-detail']")).toContainText(fixtures.public_tool_template_label);
	await page.locator("[data-input-id='prompt']").fill(fixtures.public_tool_prompt);
	await page.locator("[data-input-id='style']").selectOption("studio");
	await page.locator("[data-input-id='steps']").fill("7");

	const prepareWorkflowResponse = page.waitForResponse(apiPredicate(API.publicPrepareWorkflowFromTemplate));
	const startRunResponse = page.waitForResponse(apiPredicate(API.startRun));
	const runDetailResponse = page.waitForResponse(apiPredicate(API.publicGetMyRun));
	await page.locator("[data-action='run-tool']").click();
	const prepared = await apiJson(await prepareWorkflowResponse);
	const promptNode = prepared.message.nodes.find((node) => node.id === "prompt_1");
	expect(promptNode.config.text).toBe(fixtures.public_tool_prompt);
	expect(promptNode.config.text_style).toBe("studio");
	expect(promptNode.config.steps).toBe(7);
	const started = await apiJson(await startRunResponse);
	expect(started.message.workflow_run).toMatch(/^AI-WORKFLOW-RUN-/);
	const runDetail = await apiJson(await runDetailResponse);
	expect(runDetail.message.run.workflow_run).toBe(started.message.workflow_run);
	expect(runDetail.message.run.template_lineage.source_template_version).toBe(template.message.template_version);
	expect(runDetail.message.run.template_lineage.version_no).toBe(template.message.version_no);
	await expect(page.locator("[data-role='run-summary']")).toContainText("Status");
	await expect(page.locator("[data-role='run-history']")).toContainText("Nodes");
	await expect(page.locator("[data-role='run-detail']")).toContainText("Template Version");
	await expect(page.locator("[data-role='run-detail']")).toContainText(template.message.template_version);
	const rerunDraftResponse = page.waitForResponse(apiPredicate(API.publicPrepareRerunFromRun));
	await page.locator("[data-role='run-detail']").getByRole("button", { name: "Rerun" }).click();
	const rerunDraft = await apiJson(await rerunDraftResponse);
	expect(rerunDraft.message.workflow.source_template_version).toBe(template.message.template_version);
	expect(rerunDraft.message.template.template_version).toBe(template.message.template_version);
	expect(rerunDraft.message.prefilled_values.prompt).toBe(fixtures.public_tool_prompt);
	await expect(page.locator("[data-role='status']")).toContainText("Rerun draft ready");
	await expect(page.locator("[data-input-id='prompt']")).toHaveValue(fixtures.public_tool_prompt);
	const editedRerunPrompt = `${fixtures.public_tool_prompt} edited rerun`;
	await page.locator("[data-input-id='prompt']").fill(editedRerunPrompt);
	await page.locator("[data-input-id='style']").selectOption("natural");
	await page.locator("[data-input-id='steps']").fill("9");
	const updateRerunResponse = page.waitForResponse(apiPredicate(API.publicUpdateRerunDraftValues));
	const startRerunResponse = page.waitForResponse(apiPredicate(API.startRun));
	await page.locator("[data-action='run-tool']").click();
	const updatedRerun = await apiJson(await updateRerunResponse);
	const updatedRerunPrompt = updatedRerun.message.nodes.find((node) => node.id === "prompt_1");
	expect(updatedRerun.message.name).toBe(rerunDraft.message.workflow.name);
	expect(updatedRerun.message.source_template_version).toBe(template.message.template_version);
	expect(updatedRerunPrompt.config.text).toBe(editedRerunPrompt);
	expect(updatedRerunPrompt.config.text_style).toBe("natural");
	expect(updatedRerunPrompt.config.steps).toBe(9);
	const rerunStarted = await apiJson(await startRerunResponse);
	expect(rerunStarted.message.workflow_run).toMatch(/^AI-WORKFLOW-RUN-/);

	const legacyTemplateResponse = page.waitForResponse(apiPredicate(API.publicGetTemplate));
	await page
		.locator(`[data-template-name="${fixtures.public_legacy_template}"]`)
		.getByRole("button", { name: "Select" })
		.click();
	const legacyTemplate = await apiJson(await legacyTemplateResponse);
	expect(legacyTemplate.message.name).toBe(fixtures.public_legacy_template);
	await expect(page.locator("[data-role='template-detail']")).toContainText(fixtures.public_legacy_template_label);
	await page.locator("textarea[data-node-id='prompt_1'][data-config-field='text']").fill(fixtures.public_legacy_prompt);

	const prepareLegacyResponse = page.waitForResponse(apiPredicate(API.publicPrepareWorkflowFromTemplate));
	const startLegacyResponse = page.waitForResponse(apiPredicate(API.startRun));
	const legacyRunDetailResponse = page.waitForResponse(apiPredicate(API.publicGetMyRun));
	await page.locator("[data-action='run-tool']").click();
	const preparedLegacy = await apiJson(await prepareLegacyResponse);
	const preparedLegacyPrompt = preparedLegacy.message.nodes.find((node) => node.id === "prompt_1");
	expect(preparedLegacyPrompt.config.text).toBe(fixtures.public_legacy_prompt);
	const startedLegacy = await apiJson(await startLegacyResponse);
	expect(startedLegacy.message.workflow_run).toMatch(/^AI-WORKFLOW-RUN-/);
	await apiJson(await legacyRunDetailResponse);

	const legacyRerunDraftResponse = page.waitForResponse(apiPredicate(API.publicPrepareRerunFromRun));
	await page.locator("[data-role='run-detail']").getByRole("button", { name: "Rerun" }).click();
	const legacyRerunDraft = await apiJson(await legacyRerunDraftResponse);
	expect(legacyRerunDraft.message.workflow.source_template_version).toBe(legacyTemplate.message.template_version);
	await expect(page.locator("[data-role='status']")).toContainText("Rerun draft ready");
	const editedLegacyPrompt = `${fixtures.public_legacy_prompt} edited`;
	await page.locator("textarea[data-node-id='prompt_1'][data-config-field='text']").fill(editedLegacyPrompt);
	const updateLegacyRerunResponse = page.waitForResponse(apiPredicate(API.publicUpdateRerunDraftValues));
	const startLegacyRerunResponse = page.waitForResponse(apiPredicate(API.startRun));
	await page.locator("[data-action='run-tool']").click();
	const updatedLegacyRerun = await apiJson(await updateLegacyRerunResponse);
	const updatedLegacyPrompt = updatedLegacyRerun.message.nodes.find((node) => node.id === "prompt_1");
	expect(updatedLegacyRerun.message.name).toBe(legacyRerunDraft.message.workflow.name);
	expect(updatedLegacyRerun.message.source_template_version).toBe(legacyTemplate.message.template_version);
	expect(updatedLegacyPrompt.config.text).toBe(editedLegacyPrompt);
	const legacyRerunStarted = await apiJson(await startLegacyRerunResponse);
	expect(legacyRerunStarted.message.workflow_run).toMatch(/^AI-WORKFLOW-RUN-/);

	const refreshBeforeCancelResponse = page.waitForResponse(apiPredicate(API.publicListMyRuns));
	await page.locator("[data-action='refresh-my-runs']").click();
	await apiJson(await refreshBeforeCancelResponse);
	const cancelRunDetailResponse = page.waitForResponse(apiPredicate(API.publicGetMyRun));
	await page
		.locator(`[data-run-id="${fixtures.public_cancellable_workflow_run}"]`)
		.getByRole("button", { name: "Open Detail" })
		.click();
	const cancelRunDetail = await apiJson(await cancelRunDetailResponse);
	expect(cancelRunDetail.message.run.can_cancel).toBe(true);
	await expect(page.locator("[data-role='run-detail']")).toContainText(fixtures.public_cancellable_workflow_run);
	const cancelResponse = page.waitForResponse(apiPredicate(API.publicCancelMyRun));
	const cancelledDetailResponse = page.waitForResponse(apiPredicate(API.publicGetMyRun));
	await page.locator("[data-role='run-detail']").getByRole("button", { name: "Cancel" }).click();
	const cancelled = await apiJson(await cancelResponse);
	expect(cancelled.message.run.status).toBe("CANCELLED");
	expect(cancelled.message.run.error).toBe("Run cancelled by user.");
	const cancelledDetail = await apiJson(await cancelledDetailResponse);
	expect(cancelledDetail.message.run.status).toBe("CANCELLED");
	await expect(page.locator("[data-role='run-detail']")).toContainText("CANCELLED");
	await expect(page.locator("[data-role='run-detail']")).toContainText("Run cancelled by user.");

	const uploadTemplateResponse = page.waitForResponse(apiPredicate(API.publicGetTemplate));
	await page
		.locator(`[data-template-name="${fixtures.public_upload_template}"]`)
		.getByRole("button", { name: "Select" })
		.click();
	const uploadTemplate = await apiJson(await uploadTemplateResponse);
	expect(uploadTemplate.message.name).toBe(fixtures.public_upload_template);
	await expect(page.locator("[data-role='template-detail']")).toContainText(fixtures.public_upload_template_label);
	await page.locator("input[data-input-id='image']").fill(fixtures.public_selected_asset);

	const selectedAssetViewResponse = page.waitForResponse(apiPredicate(API.assetView));
	await page.getByRole("button", { name: "Preview Asset" }).click();
	const selectedAsset = await apiJson(await selectedAssetViewResponse);
	expect(selectedAsset.message.name).toBe(fixtures.public_selected_asset);
	await expect(page.locator(`[data-asset-name="${fixtures.public_selected_asset}"]`)).toContainText(
		fixtures.public_selected_asset
	);

	await page.locator("[data-schema-upload-url='image']").fill(fixtures.public_upload_url);
	await page.locator("[data-schema-upload-mime='image']").fill("image/png");
	const uploadResponse = page.waitForResponse(apiPredicate(API.assetUpload));
	await page.getByRole("button", { name: "Create Asset" }).click();
	const uploaded = await apiJson(await uploadResponse);
	expect(uploaded.message.url).toBe(fixtures.public_upload_url);

	const prepareUploadWorkflowResponse = page.waitForResponse(apiPredicate(API.publicPrepareWorkflowFromTemplate));
	const startUploadRunResponse = page.waitForResponse(apiPredicate(API.startRun));
	await page.locator("[data-action='run-tool']").click();
	const preparedUpload = await apiJson(await prepareUploadWorkflowResponse);
	const assetNode = preparedUpload.message.nodes.find((node) => node.id === "asset_1");
	expect(assetNode.config.asset).toBe(uploaded.message.name);
	expect(assetNode.config.asset_type).toBe("IMAGE");
	await startUploadRunResponse;

	const runListResponse = page.waitForResponse(apiPredicate(API.publicListMyRuns));
	await page.locator("[data-action='refresh-my-runs']").click();
	const runList = await apiJson(await runListResponse);
	expect(runList.message.runs.some((run) => run.workflow_run === fixtures.public_asset_workflow_run)).toBe(true);
	await expect(page.locator("[data-role='run-library']")).toContainText(fixtures.public_asset_workflow_run);

	const historyRunDetailResponse = page.waitForResponse(apiPredicate(API.publicGetMyRun));
	const historyGalleryResponse = page.waitForResponse(apiPredicate(API.publicGetRunOutputGallery));
	const historyTimelineResponse = page.waitForResponse(apiPredicate(API.runTimeline));
	await page
		.locator(`[data-run-id="${fixtures.public_asset_workflow_run}"]`)
		.getByRole("button", { name: "Open Detail" })
		.click();
	const historyRunDetail = await apiJson(await historyRunDetailResponse);
	expect(historyRunDetail.message.run.workflow_run).toBe(fixtures.public_asset_workflow_run);
	const historyGallery = await apiJson(await historyGalleryResponse);
	const historyTimeline = await apiJson(await historyTimelineResponse);
	expect(historyGallery.message.groups.length).toBeGreaterThan(0);
	expect(historyGallery.message.assets.some((asset) => asset.name === fixtures.public_history_asset)).toBe(true);
	expect(historyGallery.message.assets.some((asset) => asset.name === fixtures.public_video_history_asset)).toBe(true);
	expect(historyGallery.message.assets.some((asset) => asset.name === fixtures.public_audio_history_asset)).toBe(true);
	expect(historyTimeline.message.events.some((event) => event.event_type === "RUN_QUEUED")).toBe(true);
	await expect(page.locator("[data-role='run-detail']")).toContainText(fixtures.public_asset_workflow_run);
	await expect(page.locator("[data-role='run-timeline-detail']")).toContainText("Timeline");
	await expect(page.locator("[data-role='run-timeline-detail']")).toContainText("Run queued");
	await expect(page.locator("[data-role='run-timeline-detail']")).toContainText("Asset created");
	await page.locator("[data-role='run-timeline-detail'] [data-timeline-filter='search']").fill("Asset created");
	await expect(page.locator("[data-role='run-timeline-detail']")).toContainText("Asset created");
	await expect(page.locator("[data-role='run-timeline-detail']")).not.toContainText("Run queued");
	await page.locator("[data-role='run-timeline-detail'] [data-timeline-filter='search']").fill("no matching timeline event");
	await expect(page.locator("[data-role='run-timeline-detail']")).toContainText("No timeline events match these filters");
	await page.locator("[data-role='run-timeline-detail']").getByRole("button", { name: "Clear filters" }).click();
	await expect(page.locator("[data-role='run-timeline-detail']")).toContainText("Run queued");
	await expect(page.locator("[data-role='run-timeline-detail']")).toContainText("Asset created");
	await expect(page.locator(`[data-role='asset-output'] [data-asset-name="${fixtures.public_history_asset}"]`)).toContainText(
		fixtures.public_history_asset
	);
	await expect(page.locator(`[data-role='asset-output'] [data-asset-name="${fixtures.public_unshared_history_asset}"]`)).toContainText(
		fixtures.public_unshared_history_asset
	);
	await expect(page.locator(`[data-role='asset-output'] [data-asset-name="${fixtures.public_video_history_asset}"] video`)).toBeVisible();
	await expect(page.locator(`[data-role='asset-output'] [data-asset-name="${fixtures.public_audio_history_asset}"] audio`)).toBeVisible();
	await expect(page.locator("[data-role='asset-output'] [data-gallery-group]")).toHaveCount(1);
	await expect(page.locator("[data-role='asset-output']")).toContainText("Open Asset");
	await expect(page.locator("[data-role='asset-output']")).toContainText("Copy URL");
	await expect(page.locator("[data-role='asset-output']")).toContainText("Select All");

	await expect(page.locator(`[data-share-asset="${fixtures.public_history_asset}"]`)).toBeChecked();
	await page.locator(`[data-share-asset="${fixtures.public_unshared_history_asset}"]`).uncheck();
	await page.locator(`[data-share-asset="${fixtures.public_video_history_asset}"]`).uncheck();
	await page.locator(`[data-share-asset="${fixtures.public_audio_history_asset}"]`).uncheck();
	const createShareResponse = page.waitForResponse(apiPredicate(API.publicCreateRunShare));
	await page.locator("[data-role='run-detail']").getByRole("button", { name: "Create Share Link" }).click();
	const createdShare = await apiJson(await createShareResponse);
	expect(createdShare.message.share.status).toBe("ACTIVE");
	expect(createdShare.message.share.selected_assets).toEqual([fixtures.public_history_asset]);
	expect(createdShare.message.share.share_url).toContain("/slow-ai/shared/");
	await expect(page.locator(`article.slow-ai-tools__run-card[data-run-id="${fixtures.public_asset_workflow_run}"]`)).toContainText("Share");

	const guestContext = await browser.newContext();
	const guestPage = await guestContext.newPage();
	const guestProviderRequests = [];
	const guestTimelineRequests = [];
	guestPage.on("request", (request) => {
		const url = request.url();
		if (url.includes("api.wavespeed.ai") || url.includes("wavespeed.ai/api") || url.includes("api.replicate.com")) {
			guestProviderRequests.push(url);
		}
		if (url.includes(`/api/method/${API.runTimeline}`)) {
			guestTimelineRequests.push(url);
		}
	});
	const shareUrl = new URL(createdShare.message.share.share_url, page.url()).toString();
	const sharedRunResponse = guestPage.waitForResponse(apiPredicate(API.publicGetSharedRun));
	await guestPage.goto(shareUrl);
	const sharedRun = await apiJson(await sharedRunResponse);
	const sharedPayload = JSON.stringify(sharedRun.message);
	expect(sharedRun.message.run.workflow_run).toBe(fixtures.public_asset_workflow_run);
	expect(sharedRun.message.assets.some((asset) => asset.name === fixtures.public_history_asset)).toBe(true);
	expect(sharedRun.message.assets.some((asset) => asset.name === fixtures.public_unshared_history_asset)).toBe(false);
	expect(sharedRun.message.assets.some((asset) => asset.name === fixtures.public_video_history_asset)).toBe(false);
	expect(sharedRun.message.assets.some((asset) => asset.name === fixtures.public_audio_history_asset)).toBe(false);
	expect(sharedRun.message.output_gallery.assets.map((asset) => asset.name)).toEqual([fixtures.public_history_asset]);
	expect(sharedRun.message.output_gallery.groups.flatMap((group) => group.assets.map((asset) => asset.name))).toEqual([
		fixtures.public_history_asset,
	]);
	expect(sharedRun.message.output_gallery.groups.length).toBeGreaterThan(0);
	expect(sharedRun.message.output_gallery.run.project).toBeUndefined();
	expect(sharedRun.message.output_gallery.run.workflow).toBeUndefined();
	expect(sharedPayload).not.toContain('"project"');
	expect(sharedPayload).not.toContain('"workflow"');
	expect(sharedPayload).not.toContain(fixtures.public_tool_project);
	expect(sharedPayload).not.toContain("request_json");
	expect(sharedPayload).not.toContain("response_json");
	expect(sharedPayload).not.toContain("raw_error_json");
	await expect(guestPage.locator("[data-page='slow-ai-shared']")).toBeVisible();
	await expect(guestPage.locator("[data-role='shared-assets']")).toContainText(fixtures.public_history_asset);
	await expect(guestPage.locator("[data-role='shared-assets']")).not.toContainText(fixtures.public_unshared_history_asset);
	await expect(guestPage.locator("[data-role='shared-assets']")).not.toContainText(fixtures.public_video_history_asset);
	await expect(guestPage.locator("[data-role='shared-assets']")).not.toContainText(fixtures.public_audio_history_asset);
	await expect(guestPage.getByRole("button", { name: /^Run$/ })).toHaveCount(0);
	const guestSource = await guestPage.locator("html").innerHTML();
	expect(guestSource).not.toContain("slow_ai.api.runs.start_run");
	expect(guestSource).not.toContain("slow_ai.api.runs.get_run_timeline");
	expect(guestSource).not.toContain("Timeline");
	expect(guestSource).not.toContain("data-timeline-filter");
	expect(guestSource).not.toContain("No timeline events match these filters");
	expect(guestSource).not.toContain("WAVESPEED_API_KEY");
	expect(guestSource).not.toContain("REPLICATE_API_KEY");
	expect(guestSource).not.toContain("api_key_secret");
	expect(guestSource).not.toContain(fixtures.public_tool_project);
	expect(guestSource).not.toContain(fixtures.provider_account_label);
	expect(guestSource).not.toContain(fixtures.provider_account_secret);
	expect(guestSource).not.toContain("request_json");
	expect(guestSource).not.toContain("response_json");
	expect(guestSource).not.toContain("raw_error_json");
	expect(guestSource).not.toContain("api.wavespeed.ai");
	expect(guestSource).not.toContain("api.replicate.com");
	expect(guestSource).not.toContain("Authorization: Bearer");
	expect(guestProviderRequests).toEqual([]);
	expect(guestTimelineRequests).toEqual([]);
	await guestContext.close();

	const editorContext = await browser.newContext();
	const editorPage = await editorContext.newPage();
	await editorPage.request.post("/api/method/login", {
		form: {
			usr: fixtures.public_tool_editor_user,
			pwd: fixtures.public_tool_editor_password,
		},
	});
	const editorTemplateListResponse = editorPage.waitForResponse(apiPredicate(API.publicListTemplates));
	await editorPage.goto("/app/slow-ai-tools");
	await editorTemplateListResponse;
	await editorPage.locator("[data-role='project']").fill(fixtures.public_tool_project);
	const editorRunsResponse = editorPage.waitForResponse(apiPredicate(API.publicListMyRuns));
	await editorPage.locator("[data-action='refresh-my-runs']").click();
	const editorRuns = await apiJson(await editorRunsResponse);
	expect(editorRuns.message.runs.some((run) => run.workflow_run === fixtures.public_asset_workflow_run)).toBe(true);
	const editorTemplateResponse = editorPage.waitForResponse(apiPredicate(API.publicGetTemplate));
	await editorPage
		.locator(`[data-template-name="${fixtures.public_tool_template}"]`)
		.getByRole("button", { name: "Select" })
		.click();
	await editorTemplateResponse;
	await editorPage.locator("[data-input-id='prompt']").fill(`${fixtures.public_tool_prompt} editor`);
	const editorPrepareWorkflowResponse = editorPage.waitForResponse(apiPredicate(API.publicPrepareWorkflowFromTemplate));
	const editorStartRunResponse = editorPage.waitForResponse(apiPredicate(API.startRun));
	await editorPage.locator("[data-action='run-tool']").click();
	await editorPrepareWorkflowResponse;
	const editorStarted = await apiJson(await editorStartRunResponse);
	expect(editorStarted.message.workflow_run).toMatch(/^AI-WORKFLOW-RUN-/);
	await editorContext.close();

	const viewerContext = await browser.newContext();
	const viewerPage = await viewerContext.newPage();
	const viewerStartRequests = [];
	viewerPage.on("request", (request) => {
		if (request.url().includes(`/api/method/${API.startRun}`)) {
			viewerStartRequests.push(request.url());
		}
	});
	await viewerPage.request.post("/api/method/login", {
		form: {
			usr: fixtures.public_tool_viewer_user,
			pwd: fixtures.public_tool_viewer_password,
		},
	});
	const viewerTemplateListResponse = viewerPage.waitForResponse(apiPredicate(API.publicListTemplates));
	await viewerPage.goto("/app/slow-ai-tools");
	await viewerTemplateListResponse;
	await viewerPage.locator("[data-role='project']").fill(fixtures.public_tool_project);
	const viewerRunsResponse = viewerPage.waitForResponse(apiPredicate(API.publicListMyRuns));
	await viewerPage.locator("[data-action='refresh-my-runs']").click();
	const viewerRuns = await apiJson(await viewerRunsResponse);
	expect(viewerRuns.message.runs.some((run) => run.workflow_run === fixtures.public_asset_workflow_run)).toBe(true);
	const viewerTemplateResponse = viewerPage.waitForResponse(apiPredicate(API.publicGetTemplate));
	await viewerPage
		.locator(`[data-template-name="${fixtures.public_tool_template}"]`)
		.getByRole("button", { name: "Select" })
		.click();
	await viewerTemplateResponse;
	await viewerPage.locator("[data-input-id='prompt']").fill(`${fixtures.public_tool_prompt} viewer`);
	const viewerCreateWorkflowResponse = viewerPage.waitForResponse(apiAnyStatusPredicate(API.publicPrepareWorkflowFromTemplate));
	await viewerPage.locator("[data-action='run-tool']").click();
	const viewerCreateWorkflow = await viewerCreateWorkflowResponse;
	expect(viewerCreateWorkflow.status()).toBeGreaterThanOrEqual(400);
	expect(viewerStartRequests).toEqual([]);
	await viewerContext.close();

	await expect(page.locator("[data-role='run-detail']")).toContainText(fixtures.public_asset_workflow_run);
	const archiveRunResponse = page.waitForResponse(apiPredicate(API.publicArchiveMyRun));
	const reloadAfterArchiveResponse = page.waitForResponse(apiPredicate(API.publicListMyRuns));
	await page.locator("[data-role='run-detail']").getByRole("button", { name: "Archive" }).click();
	const archivedRun = await apiJson(await archiveRunResponse);
	expect(archivedRun.message.run.workflow_run).toBe(fixtures.public_asset_workflow_run);
	expect(archivedRun.message.run.is_archived).toBe(1);
	const runsAfterArchive = await apiJson(await reloadAfterArchiveResponse);
	expect(runsAfterArchive.message.runs.some((run) => run.workflow_run === fixtures.public_asset_workflow_run)).toBe(false);
	await expect(page.locator("[data-role='status']")).toContainText("Run archived");
	await expect(page.locator("[data-role='run-library']")).not.toContainText(fixtures.public_asset_workflow_run);

	const pageSource = await page.locator("html").innerHTML();
	expect(pageSource).not.toContain("WAVESPEED_API_KEY");
	expect(pageSource).not.toContain("REPLICATE_API_KEY");
	expect(pageSource).not.toContain("api_key_secret");
	expect(pageSource).not.toContain("api.wavespeed.ai");
	expect(pageSource).not.toContain("api.replicate.com");
	expect(pageSource).not.toContain("Authorization: Bearer");
	expect(providerRequests).toEqual([]);
});
