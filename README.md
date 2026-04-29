# Railway.app Web Terminal with Tailscale

Веб-терминал на Railway.app с интеграцией Tailscale для безопасного доступа.

## Требования

1. Аккаунт на [Railway.app](https://railway.app) (регистрация через GitHub, **карта не нужна**)
2. Auth Key от [Tailscale](https://login.tailscale.com/admin/settings/keys)

## Установка

### 1. Получите Tailscale Auth Key

1. Зайдите в [Tailscale Admin Console](https://login.tailscale.com/admin/settings/keys)
2. Создайте новый Auth Key:
   - Включите **Ephemeral** (нода удалится при остановке)
   - Включите **Reusable** (если планируете пересоздавать контейнер)
3. Скопируйте ключ (начинается с `tskey-auth-`)

### 2. Деплой на Railway

#### Вариант A: Через GitHub (рекомендуется)

1. Создайте репозиторий на GitHub и запушьте этот проект:
   ```bash
   cd /Volumes/WD/Projects/fly-terminal
   git init
   git add .
   git commit -m "Initial commit"
   git remote add origin https://github.com/ваш-username/fly-terminal.git
   git push -u origin main
   ```

2. Зайдите на [Railway.app](https://railway.app/new)
3. Нажмите **Deploy from GitHub repo**
4. Выберите ваш репозиторий `fly-terminal`
5. Railway автоматически обнаружит Dockerfile и начнет деплой

#### Вариант B: Через Railway CLI

```bash
# Установка CLI
npm i -g @railway/cli

# Логин
railway login

# Инициализация проекта
railway init

# Деплой
railway up
```

### 3. Добавьте переменные окружения

В Railway Dashboard → Variables добавьте:

```
TS_AUTHKEY=tskey-auth-XXXXXXXXXX
TERMINAL_USER=admin
TERMINAL_PASSWORD=your-secure-password
TERMINAL_SCROLLBACK=4000
FLY_TERMINAL_HISTSIZE=5000
FLY_TERMINAL_HISTFILESIZE=10000
FLY_TERMINAL_SESSION_IDLE_TTL_MINUTES=120
FLY_TERMINAL_DIAGNOSTICS=1
```

### 4. Получите URL

После деплоя Railway выдаст публичный URL типа:
```
https://fly-terminal-production.up.railway.app
```

## Использование

### Интеграция в React/Next.js приложение

```jsx
export default function Terminal() {
  return (
    <iframe 
      src="https://your-app.up.railway.app" 
      style={{ 
        width: '100%', 
        height: '600px', 
        border: 'none',
        borderRadius: '8px'
      }}
      title="Web Terminal"
    />
  );
}
```

## Безопасность

### Вариант 1: Базовая авторизация (простой)
Уже настроена через переменные `TERMINAL_USER` и `TERMINAL_PASSWORD`.

### Вариант 2: Tailscale Funnel (рекомендуется)
Для доступа только через вашу Tailscale сеть:

1. В `entrypoint.sh` добавьте после `tailscale up`:
   ```bash
   tailscale funnel $PORT
   ```

2. Доступ будет только у устройств в вашей Tailnet

## Мониторинг

В Railway Dashboard:
- **Logs**: Просмотр логов в реальном времени
- **Metrics**: CPU, RAM, Network
- **Deployments**: История деплоев

При старте контейнер теперь пишет в логи:
- лимит памяти cgroup
- текущее потребление памяти
- наличие/отсутствие swap в контейнере
- список активных процессов

Это помогает сразу отличить нехватку RAM от проблем Tailscale/ttyd/nginx.

## Стоимость

- **$5 кредитов/месяц** бесплатно (хватает на 24/7 работу терминала)
- После исчерпания кредитов: ~$5-10/месяц в зависимости от использования
- Без карты работает на бесплатных кредитах

## Troubleshooting

### Tailscale не подключается
Проверьте логи в Railway Dashboard и убедитесь, что `TS_AUTHKEY` установлен правильно.

### Терминал недоступен
1. Проверьте статус деплоя в Railway Dashboard
2. Убедитесь, что порт `PORT` правильно пробрасывается
3. Проверьте логи на ошибки

### Контейнер нестабилен по памяти
По умолчанию проект теперь ограничивает:
- `TERMINAL_SCROLLBACK=4000`
- `tmux history-limit=5000`
- `FLY_TERMINAL_HISTSIZE=5000`
- `FLY_TERMINAL_HISTFILESIZE=10000`

Старые unattached `tmux`-сессии также автоматически очищаются по TTL:
- `FLY_TERMINAL_SESSION_IDLE_TTL_MINUTES=120`

В текущей конфигурации swap внутри Railway не настраивается и не считается опорным механизмом стабилизации.

## Альтернативные регионы

Railway автоматически выбирает ближайший регион. Для изменения:
1. Settings → Region
2. Выберите: US West, US East, Europe

## Локальная разработка

```bash
# Сборка образа
docker build -t terminal .

# Запуск
docker run -p 7681:7681 \
  -e TS_AUTHKEY=your-key \
  -e TERMINAL_USER=admin \
  -e TERMINAL_PASSWORD=pass \
  terminal
```

Откройте http://localhost:7681
