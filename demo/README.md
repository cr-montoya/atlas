# Demo con datos ficticios

Una instancia de Atlas con los datos inventados de "James Restrepo", para mostrar la app sin datos reales.

- Todo lo suyo vive en `demo/datos/`. No arranca si alguna ruta de datos apunta fuera de esa carpeta, ni sigue
  enlaces simbólicos hacia otra parte.
- Sincronizar con Garmin y Polar, los análisis con agentes de IA, la imagen proyectada, la voz y escribir comidas al vault
  están apagados y se ven como "No disponible en la demo".
- Lo que alguien registre en la demo se borra con el siguiente `make demo-reset`.
- PIN: `2468`.

## Comandos

| Comando | Qué hace |
| --- | --- |
| `make demo-crear` | Instala dependencias y crea el `.env` de la demo (con `DEMO_DIR=otra/carpeta`, crea antes un worktree ahí) |
| `make demo-reset` | Borra y regenera los datos ficticios (`FECHA=` y `SEMILLA=` opcionales) |
| `make demo-run` | La demo en primer plano en http://127.0.0.1:8010 |
| `make demo-install-service` | La deja como servicio de usuario de systemd, con su alias mDNS `atlas-demo.local` |
| `make demo-restart` / `make demo-uninstall-service` | Reinicia o quita el servicio |

Para servirla en la red local con un nombre, `deploy/Caddyfile` trae el bloque de `atlas-demo.local`.
