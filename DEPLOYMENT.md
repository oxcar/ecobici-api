# Guia de Despliegue en Produccion

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
```

## Verificacion del Servicio

```bash
# Verificar estaciones
curl http://localhost:8000/api/v1/stations

# Ver metricas de contenedor
docker stats ecobici-api

# Espacio en disco usado
du -sh /var/lib/ecobici/data/*
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
