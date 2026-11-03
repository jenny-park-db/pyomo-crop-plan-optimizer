# Entry points for the demo. Settings come from .env (copy .env.example); override on the command line,
# e.g. `make bootstrap PROFILE=my-new-workspace`. Every target that talks to a workspace needs PROFILE.
-include .env
PROFILE ?= $(DATABRICKS_CONFIG_PROFILE)
TARGET ?= dev
ARGS ?=
RUN = UV_HTTP_TIMEOUT=180 uv run python

.PHONY: bootstrap grant smoke reset test check-profile

bootstrap: check-profile  ## stand the whole demo up (idempotent; ARGS="--from precompute" to resume)
	$(RUN) scripts/bootstrap.py --profile $(PROFILE) --target $(TARGET) $(ARGS)

grant: check-profile  ## give CROP_PLAN_PRESENTERS (.env) access; ARGS=--dry-run to preview
	$(RUN) scripts/grant_presenters.py --profile $(PROFILE) --target $(TARGET) $(ARGS)

smoke: check-profile  ## spec §10 at the API level (~5 min; ARGS=--skip-agent for ~20 s)
	$(RUN) scripts/smoke_test.py --profile $(PROFILE) --target $(TARGET) $(ARGS)

reset: check-profile  ## back to the bootstrapped state between demos; ARGS=--yes to delete
	$(RUN) scripts/reset_demo.py --profile $(PROFILE) --target $(TARGET) $(ARGS)

test:  ## the unit tests CI runs (root, app, agent)
	UV_HTTP_TIMEOUT=180 uv run pytest -q
	cd app && npx vitest run
	cd agent && UV_HTTP_TIMEOUT=180 uv run pytest -q

check-profile:
	@test -n "$(PROFILE)" || { echo "Set PROFILE=<databricks cli profile> or DATABRICKS_CONFIG_PROFILE in .env"; exit 2; }
