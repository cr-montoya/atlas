#!/usr/bin/env bash
# Publica NOMBRE (por defecto finanzas.local) apuntando a la IP de la interfaz con la ruta
# por defecto (no la de docker). Espera a que haya red y vuelve a publicar si la IP cambia (DHCP).
set -u
NOMBRE="${1:-finanzas.local}"
pid=""
ip=""

ip_actual() {
    ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i = 1; i < NF; i++) if ($i == "src") { print $(i + 1); exit }}'
}

parar() {
    if [ -n "$pid" ]; then kill "$pid" 2>/dev/null; wait "$pid" 2>/dev/null; fi
    pid=""
}
trap 'parar; exit 0' TERM INT

while true; do
    nueva="$(ip_actual)"
    caido=0
    if [ -n "$pid" ] && ! kill -0 "$pid" 2>/dev/null; then caido=1; fi
    if [ "$nueva" != "$ip" ] || [ "$caido" = 1 ]; then
        parar
        ip="$nueva"
        if [ -n "$ip" ]; then
            echo "Publicando $NOMBRE -> $ip"
            avahi-publish -a -R "$NOMBRE" "$ip" &
            pid=$!
        else
            echo "Sin red todavía; reintento en 15 s"
        fi
    fi
    sleep 15 &
    wait $!
done
