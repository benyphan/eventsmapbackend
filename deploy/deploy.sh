#!/bin/bash
# Деплой бэкенда на Ubuntu 22.04/24.04 (VPS).
# Запуск: sudo bash deploy.sh  (домен подставь ниже)

set -euo pipefail

DOMAIN="api.ТВОЙ-ДОМЕН.ru"
APP_DIR="/opt/eventsmap/backend"
REPO_URL=""  # например https://github.com/you/eventsmap.git

echo "==> 1. Обновление пакетов"
apt update && apt upgrade -y

echo "==> 2. Установка PostgreSQL + PostGIS + python + nginx + certbot"
apt install -y postgresql postgresql-contrib postgresql-15-postgis-3 \
  python3 python3-venv python3-pip nginx certbot python3-certbot-nginx

echo "==> 3. База данных"
sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname='events_db'" | grep -q 1 || \
  sudo -u postgres createdb events_db
sudo -u postgres psql -d events_db -c "CREATE EXTENSION IF NOT EXISTS postgis;"
sudo -u postgres psql -c "ALTER USER postgres PASSWORD 'postgres';"

echo "==> 4. Код приложения"
mkdir -p "$APP_DIR"
if [ -n "$REPO_URL" ]; then
  git clone "$REPO_URL" "$APP_DIR" || true
fi
# Если без git — скопируй папку backend на сервер вручную (scp/rsync)

echo "==> 5. Виртуальное окружение и зависимости"
cd "$APP_DIR"
python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt
chown -R www-data:www-data "$APP_DIR"
mkdir -p uploads admin_static
chown www-data:www-data uploads

echo "==> 6. systemd-сервис"
cp deploy/eventsmap.service /etc/systemd/system/
sed -i "s|WorkingDirectory=.*|WorkingDirectory=$APP_DIR|" /etc/systemd/system/eventsmap.service
sed -i "s|EnvironmentFile=.*|EnvironmentFile=$APP_DIR/.env|" /etc/systemd/system/eventsmap.service
sed -i "s|ExecStart=.*|ExecStart=$APP_DIR/venv/bin/gunicorn app.main:app -k uvicorn.workers.UvicornWorker --workers 2 --threads 4 --bind 127.0.0.1:8020 --timeout 120|" /etc/systemd/system/eventsmap.service
systemctl daemon-reload
systemctl enable eventsmap
systemctl start eventsmap || { journalctl -u eventsmap -n 50; exit 1; }

echo "==> 7. nginx + HTTPS"
cp deploy/nginx-eventsmap.conf /etc/nginx/sites-available/eventsmap
sed -i "s/api.ТВОЙ-ДОМЕН.ru/$DOMAIN/g" /etc/nginx/sites-available/eventsmap
ln -sf /etc/nginx/sites-available/eventsmap /etc/nginx/sites-enabled/eventsmap
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m admin@$DOMAIN --redirect || true

echo "==> 8. Проверка"
sleep 3
systemctl status eventsmap --no-pager | head -10
curl -s https://$DOMAIN/ && echo " <- health ok"
echo "Деплой завершён. Админка: https://$DOMAIN/admin"
