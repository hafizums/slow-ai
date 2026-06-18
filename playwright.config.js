const { defineConfig } = require("@playwright/test");
const path = require("path");

module.exports = defineConfig({
	testDir: "./e2e",
	timeout: 120000,
	expect: {
		timeout: 20000,
	},
	reporter: [["list"]],
	use: {
		baseURL: process.env.SLOW_AI_E2E_BASE_URL || "http://127.0.0.1:8001",
		viewport: { width: 1440, height: 1000 },
		actionTimeout: 20000,
		navigationTimeout: 30000,
		trace: "retain-on-failure",
	},
	metadata: {
		benchCwd: path.resolve(__dirname, "../.."),
		site: process.env.SLOW_AI_E2E_SITE || "saas",
	},
});
