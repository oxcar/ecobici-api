# Guia de Despliegue en Produccion

## Configuracion del Servidor

### Instalar Docker en Ubuntu

```bash
sudo apt update
sudo apt install -y ca-certificates curl gnupg lsb-release
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io
sudo systemctl start docker
sudo docker run hello-world
sudo usermod -aG docker $USER
docker --version
```

### Configurar zona horaria

```bash
date
timedatectl
sudo timedatectl set-timezone America/Mexico_City
sudo timedatectl set-ntp true
```

## Configuracion Inicial en el Servidor

### 1. Autenticacion con GitHub Container Registry

La imagen Docker es privada en `ghcr.io/oxcar/ecobici-api`. Para descargarla necesitas autenticarte:

```bash
# Crear un Personal Access Token (PAT) en GitHub:
# 1. Ve a GitHub Settings > Developer settings > Personal access tokens > Tokens (classic)
# 2. Generate new token (classic)
# 3. Selecciona el scope: read:packages
# 4. Copia el token

# Login en el servidor
echo "TU_TOKEN_GITHUB" | docker login ghcr.io -u oxcar --password-stdin
```

### 2. Crear estructura de directorios

```bash
# Crear directorio base
sudo mkdir -p /var/lib/ecobici/data

# Copiar modelos desde tu maquina local
scp -r data/models usuario@servidor:/tmp/
ssh usuario@servidor "sudo mv /tmp/models /var/lib/ecobici/data/"

# Configurar permisos
sudo chown -R oscar:oscar /var/lib/ecobici
```

### 3. Preparar archivos de configuracion

```bash
# Clonar o copiar archivos necesarios
cd /home/oscar
git clone https://github.com/oxcar/ecobici-api.git
cd ecobici-api

# El archivo .env.production ya esta listo (todo comentado, usa defaults)
# Solo copialo si necesitas sobrescribir algun valor
# cp .env.production .env
```

### 4. Iniciar servicio

```bash
# Descargar imagen mas reciente
docker-compose pull

# Iniciar en segundo plano
docker-compose up -d

# Ver logs
docker-compose logs -f

# Verificar estado
curl http://localhost:8000/api/v1/health
```

## Estructura de Datos en Produccion

```
/var/lib/ecobici/data/
├── models/
│   ├── xgboost/
│   │   ├── model_20min.pkl
│   │   ├── model_40min.pkl
│   │   └── model_60min.pkl
│   └── lstm/
│       ├── model.pth
│       ├── model_config.pkl
│       └── scaler.pkl
├── gbfs/              # Creado automaticamente por el collector
│   └── year=YYYY/month=MM/gbfs_YYYYMMDD.parquet
├── statistics/        # Creado automaticamente
│   └── year=YYYY/month=MM/stats_YYYYMMDD.parquet
└── cache/            # Creado automaticamente
    ├── history/
    └── averages/
```

## Actualizacion de la Imagen

```bash
cd /home/oscar/ecobici-api

# Descargar nueva version
docker-compose pull

# Reiniciar con nueva imagen
docker-compose up -d

# Verificar logs
docker-compose logs -f --tail=50
```

## Mantenimiento

### Ver logs en tiempo real
```bash
docker-compose logs -f
```

### Reiniciar servicio
```bash
docker-compose restart
```

### Detener servicio
```bash
docker-compose down
```

### Limpiar imagenes antiguas
```bash
docker image prune -a
```

### Backup de datos
```bash
# Backup de modelos y datos historicos
sudo tar -czf /backup/ecobici-data-$(date +%Y%m%d).tar.gz /var/lib/ecobici/data

# Backup con compresion paralela usando pigz
tar -cf - /var/lib/ecobici/data | pigz -p 4 > /backup/ecobici-data-$(date +%Y%m%d).tar.gz

# Copiar backup desde servidor remoto usando rsync
rsync -avz --progress oscar@servidor:/backup/ecobici-data-*.tar.gz ./backups/
```

## Verificacion del Servicio

```bash
# Verificar estaciones
curl http://localhost:8000/api/v1/stations

# Ver metricas de contenedor
docker stats ecobici-api

# Espacio en disco usado
du -sh /var/lib/ecobici/data/*

# Inspeccionar volumenes Docker
docker volume ls
docker volume inspect ecobici_data_volume

# Acceder al contenedor
docker exec -it ecobici-api sh
```

## Comandos Utiles

### Docker Compose Aliases
```bash
# Agregar a ~/.bashrc o ~/.zshrc
alias dcu="docker compose up -d"
alias dcb="docker compose up -d --build"
alias dcl="docker compose logs -f"
alias dcd="docker compose down"
```

### Comandos Docker Compose
```bash
# Construir imagen
docker compose build

# Iniciar servicios
docker compose up -d

# Ver logs en tiempo real
docker compose logs -f

# Detener servicios
docker compose down
```

## Troubleshooting

### El contenedor no inicia
```bash
# Ver logs completos
docker-compose logs

# Ver eventos del contenedor
docker events --filter container=ecobici-api
```

### Problemas de permisos
```bash
# Verificar propietario
ls -la /var/lib/ecobici/data

# Corregir permisos
sudo chown -R oscar:oscar /var/lib/ecobici
```

### El recolector no guarda datos
```bash
# Verificar que el collector este habilitado
docker-compose exec ecobici-api env | grep COLLECTOR

# Ver logs del collector
docker-compose logs -f | grep collector
```

## Exposicion Publica con Cloudflare Tunnel

### Ventajas de Cloudflare Tunnel

- No necesitas abrir puertos en el firewall
- Proteccion DDoS automatica
- SSL/TLS automatico y gratuito
- Oculta la IP real del servidor
- Cache y optimizacion de contenido
- Sin costo adicional

### Requisitos Previos

1. Cuenta en Cloudflare (gratuita)
2. Dominio configurado en Cloudflare (puede ser subdominio)
3. Servidor con Docker ejecutando la API

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

### Actualizar docker-compose.yml

Actualiza para que solo escuche en localhost (mas seguro):

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

### Configuracion Avanzada de Cloudflare

#### Habilitar Cache

En el Dashboard de Cloudflare:
1. Ve a tu dominio > Caching > Configuration
2. Agrega reglas de cache:
   - `/api/v1/history/*` → Cache Level: Standard, TTL: 10 minutos

#### Rate Limiting

1. Ve a Security > WAF > Rate limiting rules
2. Crea regla:
   - **Nombre**: API Rate Limit
   - **Si**: Incoming requests match `api.tu-dominio.com/api/v1/predict*`
   - **Entonces**: Block
   - **Durante**: 60 segundos
   - **Cuando la tasa excede**: 100 requests por minuto

#### Proteccion DDoS

1. Ve a Security > DDoS
2. Habilita:
   - HTTP DDoS Attack Protection (Managed Ruleset)
   - Advanced DDoS Protection

### Monitoreo del Tunnel

```bash
# Ver logs del tunnel
sudo journalctl -u cloudflared -f

# Verificar conectividad
cloudflared tunnel info ecobici-api
```

### Troubleshooting Cloudflare Tunnel

#### El tunnel no conecta
```bash
# Verificar servicio
sudo systemctl status cloudflared

# Ver logs detallados
sudo journalctl -u cloudflared -n 100

# Reiniciar servicio
sudo systemctl restart cloudflared
```

#### Error 502 Bad Gateway
- Verifica que la API este corriendo: `docker ps`
- Verifica que responda localmente: `curl http://localhost:8000/api/v1/health`
- Revisa logs de Docker: `docker-compose logs -f`

#### DNS no resuelve
- Verifica en Cloudflare Dashboard que el CNAME este creado
- Espera unos minutos para propagacion DNS
- Prueba con: `nslookup api.tu-dominio.com`

### Multiples Servicios

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

### Backup de Configuracion del Tunnel

```bash
# Backup del tunnel
sudo cp /root/.cloudflared/*.json ~/cloudflared-backup/
sudo cp /etc/cloudflared/config.yml ~/cloudflared-backup/

# Listar tunnels
cloudflared tunnel list > ~/cloudflared-backup/tunnels.txt
```

### Desinstalar Tunnel

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
- [Docker Documentation](https://docs.docker.com)
