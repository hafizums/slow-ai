#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${SLOW_AI_E2E_BASE_URL:-http://127.0.0.1:8001}"
SITE="${SLOW_AI_E2E_SITE:-saas}"
LOG_FILE="logs/slow_ai_e2e_web.log"
STARTED_PID=""

cleanup() {
	if [[ -n "${STARTED_PID}" ]] && kill -0 "${STARTED_PID}" >/dev/null 2>&1; then
		kill "${STARTED_PID}" >/dev/null 2>&1 || true
		wait "${STARTED_PID}" >/dev/null 2>&1 || true
	fi
	if [[ "${SLOW_AI_E2E_CLEANUP_DATA:-1}" != "0" ]]; then
		bench --site "${SITE}" execute slow_ai.tests.e2e.fixtures.cleanup_canvas_e2e >/dev/null 2>&1 || true
	fi
}
trap cleanup EXIT

server_ready() {
	curl -fsS "${BASE_URL}/login" >/dev/null 2>&1
}

if ! server_ready; then
	mkdir -p logs
	PORT="$(
		SLOW_AI_E2E_BASE_URL="${BASE_URL}" node -e "const url = new URL(process.env.SLOW_AI_E2E_BASE_URL); console.log(url.port || (url.protocol === 'https:' ? '443' : '80'));"
	)"
	bench --site "${SITE}" serve --port "${PORT}" --noreload >"${LOG_FILE}" 2>&1 &
	STARTED_PID="$!"
	for _ in $(seq 1 60); do
		if server_ready; then
			break
		fi
		sleep 1
	done
	if ! server_ready; then
		echo "Frappe web server did not become ready at ${BASE_URL}. See ${LOG_FILE}." >&2
		exit 1
	fi
fi

npx playwright install chromium
npx playwright test --config=apps/slow_ai/playwright.config.js
