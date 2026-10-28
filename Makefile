.PHONY: demo-crear demo-reset demo-actualizar demo-run demo-install-service demo-uninstall-service demo-restart run test e2e backup seed env resumen-ia resumen-rendimiento cargar-tests install-service uninstall-service restart status logs

# make run es para desarrollo, solo en este equipo. El uso diario va por el servicio
# (make install-service) detrás de Caddy en http://finanzas.local.
HOST ?= 127.0.0.1
PORT ?= 8001
UNIDADES = finanzas.service finanzas-alias.service atlas-alias.service
SYSTEMD_USER = $(HOME)/.config/systemd/user

run:
	uv run uvicorn app.main:crear_app --factory --host $(HOST) --port $(PORT)

test:
	uv run pytest -q

e2e:
	NODE_PATH=.claude/skills/playwright-skill/node_modules node tests/e2e/registro_rapido.js

seed:
	uv run python -m app.modules.finanzas.seed

resumen-rendimiento:
	uv run python -m app.modules.rendimiento.resumen_ia

cargar-tests:
	uv run python -m app.modules.rendimiento.carga_tests

resumen-ia:
	uv run python -m app.modules.finanzas.resumen_ia

backup:
	@mkdir -p backups
	@test -f data/finanzas.db || (echo "No hay base en data/finanzas.db" && exit 1)
	uv run python -c "import sqlite3, datetime; s = sqlite3.connect('data/finanzas.db'); d = sqlite3.connect('backups/finanzas-' + datetime.datetime.now().strftime('%Y-%m-%d-%H%M') + '.db'); s.backup(d); d.close(); s.close()"
	@ls -1t backups | head -1

env:
	@test -f .env && echo ".env ya existe" || (sed "s/^BRAIN_SECRETO=.*/BRAIN_SECRETO=$$(uv run python -c 'import secrets; print(secrets.token_urlsafe(32))')/" .env.example > .env && chmod 600 .env && echo "Creado .env: cambia BRAIN_PIN")

install-service:
	@test -f .env || (echo "Falta .env: corre make env" && exit 1)
	@mkdir -p $(SYSTEMD_USER)
	cp $(addprefix deploy/,$(UNIDADES)) $(SYSTEMD_USER)/
	systemctl --user daemon-reload
	systemctl --user enable --now $(UNIDADES)
	@systemctl --user --no-pager status $(UNIDADES) | grep -E "●|Active:"

uninstall-service:
	-systemctl --user disable --now $(UNIDADES)
	rm -f $(addprefix $(SYSTEMD_USER)/,$(UNIDADES))
	systemctl --user daemon-reload

restart:
	systemctl --user restart $(UNIDADES)

status:
	@systemctl --user --no-pager status $(UNIDADES)

logs:
	journalctl --user -u finanzas -u finanzas-alias -u atlas-alias -f

# ---------- Demo con datos ficticios (ver demo/README.md) ----------
# Por defecto corre desde este clon. Si aquí también corre tu app real, usa otro worktree: make demo-crear DEMO_DIR=../atlas-demo
DEMO_DIR ?= $(CURDIR)
UNIDADES_DEMO = atlas-demo.service atlas-demo-alias.service
EN_DEMO = cd $(DEMO_DIR) && BRAIN_DEMO=1

demo-crear:
	@test -d $(DEMO_DIR) || git worktree add --detach $(DEMO_DIR) main
	cd $(DEMO_DIR) && uv sync --frozen
	@test -f $(DEMO_DIR)/.env && echo "La demo ya tiene .env" || (sed "s/^BRAIN_SECRETO=.*/BRAIN_SECRETO=$$(uv run python -c 'import secrets; print(secrets.token_urlsafe(32))')/" $(DEMO_DIR)/demo/.env.example > $(DEMO_DIR)/.env && chmod 600 $(DEMO_DIR)/.env && echo "Creado $(DEMO_DIR)/.env (PIN 2468)")

demo-reset:
	$(EN_DEMO) uv run python -m app.demo $(if $(FECHA),--fecha $(FECHA)) $(if $(SEMILLA),--semilla $(SEMILLA))
	@if systemctl --user is-active --quiet atlas-demo.service; then systemctl --user restart atlas-demo.service; fi

demo-actualizar:
	git -C $(DEMO_DIR) checkout --detach main
	cd $(DEMO_DIR) && uv sync --frozen
	@if systemctl --user is-active --quiet atlas-demo.service; then systemctl --user restart atlas-demo.service; fi

demo-run:
	$(EN_DEMO) uv run uvicorn app.main:crear_app --factory --host 127.0.0.1 --port 8010

demo-install-service:
	@test -f $(DEMO_DIR)/.env || (echo "Falta la demo: corre make demo-crear y make demo-reset" && exit 1)
	@mkdir -p $(SYSTEMD_USER)
	cp $(addprefix deploy/,$(UNIDADES_DEMO)) $(SYSTEMD_USER)/
	systemctl --user daemon-reload
	systemctl --user enable --now $(UNIDADES_DEMO)
	@systemctl --user --no-pager status $(UNIDADES_DEMO) | grep -E "●|Active:"

demo-uninstall-service:
	-systemctl --user disable --now $(UNIDADES_DEMO)
	rm -f $(addprefix $(SYSTEMD_USER)/,$(UNIDADES_DEMO))
	systemctl --user daemon-reload

demo-restart:
	systemctl --user restart $(UNIDADES_DEMO)
