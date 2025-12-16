# Configuracion de Cloudflare Tunnel

Esta guia explica como exponer la API de Ecobici al mundo usando Cloudflare Tunnel.

## Ventajas de Cloudflare Tunnel

- ✅ No necesitas abrir puertos en el firewall
- ✅ Proteccion DDoS automatica
- ✅ SSL/TLS automatico y gratuito
- ✅ Oculta la IP real del servidor
- ✅ Cache y optimizacion de contenido
- ✅ Sin costo adicional

## Requisitos Previos

1. Cuenta en Cloudflare (gratuita)
2. Dominio configurado en Cloudflare (puede ser subdominio)
3. Servidor con Docker ejecutando la API

## Configuracion Paso a Paso

### 1. Instalar cloudflared en el Servidor

```bash
# Descargar cloudflared
wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb

# Instalar
sudo dpkg -i cloudflared-linux-amd64.deb

# Verificar instalacion
cloudflared version
```

### 2. Autenticarse con Cloudflare

```bash
# Iniciar autenticacion (abrira navegador)
cloudflared tunnel login
```

Esto abrira tu navegador para autorizar cloudflared con tu cuenta de Cloudflare.

### 3. Crear el Tunnel

```bash
# Crear tunnel llamado "ecobici-api"
cloudflared tunnel create ecobici-api

# Listar tunnels creados
cloudflared tunnel list
```

Guarda el **Tunnel ID** que se muestra (formato: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx).

### 4. Configurar el Tunnel

Crea el archivo de configuracion:

```bash
sudo mkdir -p /etc/cloudflared
sudo nano /etc/cloudflared/config.yml
```

Contenido del archivo (ajusta `tunnel-id` y `tu-dominio.com`):

```yaml
tunnel: TUNNEL-ID-AQUI
credentials-file: /root/.cloudflared/TUNNEL-ID-AQUI.json

ingress:
  # Ruta para la API
  - hostname: api.tu-dominio.com
    service: http://localhost:8000
    originRequest:
      noTLSVerify: true
  
  # Catch-all rule (requerido)
  - service: http_status:404
```

### 5. Configurar DNS en Cloudflare

```bash
# Asociar dominio con el tunnel
cloudflared tunnel route dns ecobici-api api.tu-dominio.com
```

Esto creara automaticamente un registro DNS CNAME en Cloudflare apuntando a tu tunnel.

### 6. Iniciar el Tunnel como Servicio

```bash
# Instalar como servicio systemd
sudo cloudflared service install

# Iniciar servicio
sudo systemctl start cloudflared

# Habilitar en inicio automatico
sudo systemctl enable cloudflared

# Verificar estado
sudo systemctl status cloudflared
```

### 7. Verificar Configuracion

```bash
# Verificar logs del tunnel
sudo journalctl -u cloudflared -f

# Probar endpoint
curl https://api.tu-dominio.com/api/v1/health
```

## Configuracion de Docker Compose

Actualiza `docker-compose.yml` para que solo escuche en localhost (mas seguro):

```yaml
services:
  ecobici-api:
    image: ghcr.io/oxcar/ecobici-api:latest
    container_name: ecobici-api
    restart: unless-stopped
    ports:
      - "127.0.0.1:8000:8000"  # Solo localhost
    # ...resto de configuracion
```

Reinicia el contenedor:
```bash
docker-compose up -d
```

## Configuracion Avanzada de Cloudflare

### Habilitar Cache (opcional)

En el Dashboard de Cloudflare:
1. Ve a tu dominio > Caching > Configuration
2. Agrega reglas de cache:
   - `/api/v1/history/*` → Cache Level: Standard, TTL: 10 minutos


### Rate Limiting (recomendado)

1. Ve a Security > WAF > Rate limiting rules
2. Crea regla:
   - **Nombre**: API Rate Limit
   - **Si**: Incoming requests match `api.tu-dominio.com/api/v1/predict*`
   - **Entonces**: Block
   - **Durante**: 60 segundos
   - **Cuando la tasa excede**: 100 requests por minuto

### Proteccion DDoS

1. Ve a Security > DDoS
2. Habilita:
   - HTTP DDoS Attack Protection (Managed Ruleset)
   - Advanced DDoS Protection

## Monitoreo y Logs

### Ver logs del tunnel
```bash
sudo journalctl -u cloudflared -f
```

### Metricas en Dashboard de Cloudflare
1. Ve a tu dominio > Analytics > Traffic
2. Observa:
   - Requests por minuto
   - Bandwidth usado
   - Status codes
   - Top paths

### Verificar conectividad del tunnel
```bash
cloudflared tunnel info ecobici-api
```

## Troubleshooting

### El tunnel no conecta

```bash
# Verificar servicio
sudo systemctl status cloudflared

# Ver logs detallados
sudo journalctl -u cloudflared -n 100

# Reiniciar servicio
sudo systemctl restart cloudflared
```

### Error 502 Bad Gateway

- Verifica que la API este corriendo: `docker ps`
- Verifica que responda localmente: `curl http://localhost:8000/api/v1/stations`
- Revisa logs de Docker: `docker-compose logs -f`

### DNS no resuelve

- Verifica en Cloudflare Dashboard que el CNAME este creado
- Espera unos minutos para propagacion DNS
- Prueba con: `nslookup api.tu-dominio.com`

## Multiples Servicios (Avanzado)

Si quieres exponer mas servicios a traves del mismo tunnel:

```yaml
ingress:
  # API de produccion
  - hostname: api.tu-dominio.com
    service: http://localhost:8000
  
  # Panel de monitoreo (ejemplo)
  - hostname: monitor.tu-dominio.com
    service: http://localhost:3000
  
  # Catch-all
  - service: http_status:404
```

## Backup de Configuracion

```bash
# Backup del tunnel
sudo cp /root/.cloudflared/*.json ~/cloudflared-backup/
sudo cp /etc/cloudflared/config.yml ~/cloudflared-backup/

# Listar tunnels
cloudflared tunnel list > ~/cloudflared-backup/tunnels.txt
```

## Desinstalar Tunnel

```bash
# Detener servicio
sudo systemctl stop cloudflared
sudo systemctl disable cloudflared

# Eliminar tunnel
cloudflared tunnel delete ecobici-api

# Desinstalar cloudflared
sudo apt remove cloudflared
```

## Recursos Adicionales

- [Documentacion oficial de Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/)
- [Dashboard de Cloudflare](https://dash.cloudflare.com)
- [Comunidad de Cloudflare](https://community.cloudflare.com)
