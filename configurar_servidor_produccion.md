## crear tar.gz con compresión paralela usando pigz
tar -cf - /home/oscar/data/ecobici/gbfs/2025/10 | pigz -p 4 > backup/2025_10.tar.gz

## copiar archivo desde servidor remoto usando rsync con progreso
rsync -avz --progress oscar@nomu:/home/oscar/data/backup/2025_\*.tar.gz .


docker ps
docker volume ls
docker volume inspect ecobici_data_volume
docker exec -it <container> sh

## Configurar hora en el servidor
date
timedatectl
sudo timedatectl set-timezone America/Mexico_City
sudo timedatectl set-ntp true


## Instalar Docker en Ubuntu
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

## Ejecutar docker compose build para el servicio scraper
docker compose build scraper    
## Ejecutar el servicio scraper en segundo plano
docker compose up -d scraper
## Ejecutar docker compose build para el servicio etl
docker compose up -d etl

## Aliases para docker compose
alias dcu="docker compose up -d"
alias dcb="docker compose up -d --build"
alias dcl="docker compose logs -f"
alias dcd="docker compose down"