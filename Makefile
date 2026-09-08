# Wins Pool — dev tasks and Pi operations.
# `make` with no target lists everything.

SHELL := /bin/bash
.DEFAULT_GOAL := help

APP_DIR ?= /home/nate/awardwinninglisteners
DB      ?= /var/lib/winspool/league.db
PORT    ?= 8080
SINCE   ?= 1 hour ago
N       ?= 50

.PHONY: help
help:  ## List available targets
	@echo "Wins Pool — make targets"
	@awk 'BEGIN {FS = ":.*?## "} \
		/^# ==/ {sub(/^# == /, ""); printf "\n\033[1m%s\033[0m\n", $$0} \
		/^[a-zA-Z0-9_-]+:.*?## / {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo

# == Development

.PHONY: install
install:  ## Install Python and web dependencies
	uv sync --extra dev
	cd web && npm ci

.PHONY: test
test:  ## Run the Python test suite
	uv run pytest -q

.PHONY: lint
lint:  ## Lint the front end (same check CI runs)
	cd web && npx oxlint src

.PHONY: build
build:  ## Build the front end into web/dist
	cd web && npm run build

.PHONY: check
check: test build lint  ## Everything CI runs, in one go

.PHONY: serve
serve:  ## Run the app locally on :8000 with an in-memory dev league (PINs 1234)
	uv run winspool-serve

.PHONY: refresh-ratings
refresh-ratings:  ## Fetch fresh power ratings + Kalshi, commit CSVs on a branch, push (run weekly from a laptop)
	@test "$$(git rev-parse --abbrev-ref HEAD)" != "main" || { echo "switch off main first: git checkout -b ratings/$$(date +%F)"; exit 1; }
	uv run winspool fetch
	git checkout -- data/cache/win_totals.csv
	git add data/cache/power_ratings.csv data/cache/kalshi_distributions.csv data/cache/sources_meta.json
	git diff --cached --quiet || git commit -m "data: ratings refresh $$(date +%F)"
	git push -u origin HEAD
	@echo "open a PR into main, merge, then 'make deploy' on the Pi"

.PHONY: clean
clean:  ## Remove build output and caches
	rm -rf web/dist web/node_modules/.vite .pytest_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

# == Pi operations (this machine)

.PHONY: status
status:  ## Dashboard: services, resources, endpoint, tunnel, database
	@printf "\033[1m%-13s %-9s %-8s %-7s %s\033[0m\n" SERVICE STATE MEM CPU UPTIME
	@for u in winspool cloudflared; do \
		pid=$$(systemctl show $$u -p MainPID --value); \
		state=$$(systemctl is-active $$u); \
		stats=$$(ps -o rss=,pcpu=,etime= -p "$$pid" 2>/dev/null | \
			awk '{printf "%.0f MB|%s%%|%s", $$1/1024, $$2, $$3}'); \
		printf "%-13s %-9s %-8s %-7s %s\n" "$$u" "$$state" \
			"$$(cut -d'|' -f1 <<<"$$stats")" "$$(cut -d'|' -f2 <<<"$$stats")" \
			"$$(cut -d'|' -f3 <<<"$$stats")"; \
	done
	@echo
	@code=$$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 \
		http://127.0.0.1:$(PORT)/api/teams 2>/dev/null); \
		echo "endpoint    127.0.0.1:$(PORT)/api/teams -> $$code"
	@echo "tunnel      $$(cloudflared tunnel info pi 2>/dev/null | grep -oE '[0-9]+x[a-z0-9]+' | \
		awk -F'x' '{s+=$$1} END {print s+0}') edge connections ($$(systemctl is-active cloudflared))"
	@echo "database    $$($(MAKE) --no-print-directory db-summary 2>/dev/null | tr '\n' ' ' | tr -s ' ')"
	@echo "next timer  $$(systemctl list-timers 'winspool*' --no-pager 2>/dev/null | sed -n '2p' | awk '{print $$1, $$2, $$3, $$4, $$5}')"

.PHONY: up
up:  ## Start the app
	sudo systemctl start winspool
	@$(MAKE) --no-print-directory health

.PHONY: down
down:  ## Stop the app (visitors get a Cloudflare 502)
	sudo systemctl stop winspool

.PHONY: restart
restart:  ## Restart the app (picks up /etc/winspool/env changes)
	sudo systemctl restart winspool
	@$(MAKE) --no-print-directory health

.PHONY: health
health:  ## Poll the local health endpoint until it answers
	@for i in $$(seq 1 60); do \
		if curl -fsS http://127.0.0.1:$(PORT)/api/teams >/dev/null 2>&1; then \
			echo "healthy after $${i}s"; exit 0; fi; \
		sleep 1; \
	done; \
	echo "NOT healthy after 60s"; journalctl -u winspool -n 40 --no-pager; exit 1

.PHONY: logs
logs:  ## Follow the app log (Ctrl-C to stop)
	journalctl -u winspool -f

.PHONY: logs-recent
logs-recent:  ## App log since SINCE=... (default: 1 hour ago)
	journalctl -u winspool --since '$(SINCE)' --no-pager

.PHONY: tunnel
tunnel:  ## Tunnel status and edge connections
	@systemctl is-active cloudflared
	@cloudflared tunnel info pi 2>&1 | tail -3
	@sudo cloudflared --config /etc/cloudflared/config.yml tunnel ingress validate

.PHONY: tunnel-logs
tunnel-logs:  ## Last N=... lines of the tunnel log
	journalctl -u cloudflared -n $(N) --no-pager

.PHONY: timers
timers:  ## When the next standings refresh and backup fire
	@systemctl list-timers 'winspool*' --no-pager

.PHONY: deploy
deploy:  ## Pull main, rebuild, restart, health-check
	sudo $(APP_DIR)/scripts/pi-deploy.sh

.PHONY: ship
ship:  ## Build and serve the CURRENT checkout (no git pull), then health-check
	@echo "shipping $$(git rev-parse --abbrev-ref HEAD) @ $$(git rev-parse --short HEAD)"
	uv sync --extra dev
	cd web && npm run build
	sudo systemctl restart winspool
	@$(MAKE) --no-print-directory health

# == Preview (temporary public URL, no DNS change)

.PHONY: preview
preview: ship preview-stop  ## Ship the current checkout and expose it at a fresh *.trycloudflare.com URL
	@# --config /dev/null: as root, cloudflared would otherwise load the named
	@# tunnel's /etc/cloudflared/config.yml, whose ingress 404s every other host.
	sudo systemd-run --quiet --collect --unit=winspool-quick \
	  cloudflared --config /dev/null tunnel --url http://127.0.0.1:$(PORT)
	@$(MAKE) --no-print-directory preview-url

.PHONY: preview-url
preview-url:  ## Print the current preview URL
	@for i in $$(seq 1 30); do \
		url=$$(journalctl -u winspool-quick --no-pager -o cat 2>/dev/null \
		       | grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' | tail -1); \
		if [ -n "$$url" ]; then echo "$$url"; exit 0; fi; sleep 1; \
	done; echo "no preview URL yet — is winspool-quick running? (make preview)"; exit 1

.PHONY: preview-stop
preview-stop:  ## Stop the preview tunnel (the real domain is unaffected)
	@sudo systemctl stop winspool-quick 2>/dev/null || true

.PHONY: refresh
refresh:  ## Force a standings refresh now
	sudo systemctl start winspool-scores.service
	@journalctl -u winspool-scores -n 3 --no-pager | tail -3

.PHONY: backup
backup:  ## Take a database backup now
	sudo systemctl start winspool-backup.service
	@sudo ls -la /var/backups/winspool/ | tail -5

.PHONY: load
load:  ## Live CPU/memory per service
	systemd-cgtop

# == Database

.PHONY: db
db:  ## Open a SQLite shell on the live database
	sudo -u winspool sqlite3 $(DB)

.PHONY: db-summary
db-summary:  ## One-line summary of what the database holds
	@sudo -u winspool sqlite3 $(DB) \
	  "select 'status=' || json_extract(doc,'$$.status') || \
	          '  picks=' || json_array_length(json_extract(doc,'$$.picks')) from league;" \
	  2>/dev/null || echo "no league initialized"
	@echo "messages=$$(sudo -u winspool sqlite3 $(DB) 'select count(*) from messages;')" \
	      "snapshots=$$(sudo -u winspool sqlite3 $(DB) 'select count(*) from snapshots;')"

.PHONY: export
export:  ## Export the live database to OUT=... (default league_export.json)
	@out="$${OUT:-$(PWD)/league_export.json}"; \
	stage=/var/lib/winspool/.export.json; \
	sudo -u winspool env $$(sudo grep -v '^#' /etc/winspool/env | xargs) \
	  $(APP_DIR)/.venv/bin/winspool export --out "$$stage"; \
	sudo mv "$$stage" "$$out"; \
	sudo chown $$(id -u):$$(id -g) "$$out"; \
	chmod 600 "$$out"; \
	echo "wrote $$out (mode 600 — contains PIN hashes, do not commit)"; \
	ls -la "$$out"
