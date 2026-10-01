# pc-remote-bot

**English** · [Русский](README.ru.md)

Telegram bot to wake up and control a Windows PC remotely: Wake-on-LAN, status, screenshots,
processes, PowerShell commands, lock / sleep / reboot / shutdown.

## Features

| Command | Button | What it does |
| --- | --- | --- |
| `/wake` | ⚡ Включить ПК | Sends a Wake-on-LAN magic packet and reports when the PC is up |
| `/ping` | 📡 Проверить ПК | Checks whether the PC answers ping |
| `/status` | 📊 Статус | CPU, memory, disks, uptime |
| `/screen` | 🖥 Скриншот | Screenshot of all monitors |
| `/ps` | 📋 Процессы | Top processes by memory |
| `/kill chrome` or `/kill 1234` | ❌ Завершить процесс | Kills a process by name or PID |
| `/cmd Get-Date` | ⌨️ PowerShell | Runs a PowerShell command (60 s timeout) |
| `/lock` | 🔒 Заблокировать | Locks the screen |
| `/sleep` | 😴 Сон | Puts the PC to sleep |
| `/reboot` | 🔄 Перезагрузка | Reboots in 30 s (with confirmation) |
| `/shutdown` | ⏻ Выключить | Shuts down in 30 s (with confirmation) |
| `/cancel` | ↩️ Отменить выключение | Cancels a pending shutdown / reboot |

The bot UI is in Russian. Only users listed in `ALLOWED_USER_IDS` can use it; everyone else
gets "access denied" along with their Telegram ID.

## How it works

The same code runs in two roles, chosen by `.env`:

- **On the PC** (`ENABLE_CONTROL=true`): everything except waking it up.
- **On an always-on device in the same LAN** (a second PC, a laptop, a Raspberry Pi), with
  `WOL_MAC` set: `/wake` and `/ping`. A powered-off PC cannot wake itself up, so this part has
  to live elsewhere.

You can run both roles with one bot token only if they never run at the same time. Otherwise
create two bots in @BotFather.

## Requirements

- Windows 10/11 (control commands use Windows tools)
- [uv](https://docs.astral.sh/uv/) (it installs Python 3.12+ itself)
- A bot token from [@BotFather](https://t.me/BotFather)

## Setup

1. Clone and install dependencies:

   ```powershell
   git clone https://github.com/namadeku/pc-remote-bot.git
   cd pc-remote-bot
   uv sync
   ```

2. Create the config:

   ```powershell
   Copy-Item env.example .env
   ```

   Open `.env` and set `BOT_TOKEN`.

3. Get your Telegram ID: run the bot (`uv run pc-remote-bot`), send it `/start`, and it will
   reply with your ID. Put it in `ALLOWED_USER_IDS` and restart the bot.

4. Send `/start` again, and the keyboard with all actions appears.

### Settings (`.env`)

| Variable | Description |
| --- | --- |
| `BOT_TOKEN` | Token from @BotFather (required) |
| `ALLOWED_USER_IDS` | Comma-separated Telegram user IDs allowed to use the bot |
| `ENABLE_CONTROL` | `true` on the PC itself: enables status, screenshots, power commands |
| `WOL_MAC` | MAC address of the PC's **wired** adapter; enables `/wake` |
| `WOL_HOST` | LAN broadcast address (e.g. `192.168.1.255`), or the router's public address / DDNS name if it forwards UDP |
| `WOL_PORT` | Wake-on-LAN port, usually `9` |
| `PC_HOST` | The PC's LAN IP, for `/ping` and the "PC is up" notification |
| `PROXY_URL` | Optional proxy for Telegram, e.g. `socks5://127.0.0.1:10808` |

### Wake-on-LAN checklist

- Enable **Wake on LAN** / **Power On by PCI-E** in the BIOS/UEFI.
- In Device Manager → network adapter → *Power Management*, allow it to wake the computer;
  on *Advanced*, enable *Wake on Magic Packet*.
- Disable **Fast Startup** (Control Panel → Power Options → *Choose what the power buttons do*).
- Use a wired connection: most Wi-Fi adapters cannot wake a PC.
- Find the MAC with `Get-NetAdapter | Select Name, MacAddress`.

## Autostart

The bot can run without a console window under `pythonw`. Logs then go to `bot.log` in the
project folder.

1. Press `Win+R`, type `shell:startup`, and press Enter.
2. Create a shortcut there with:
   - **Target:** `C:\path\to\pc-remote-bot\.venv\Scripts\pythonw.exe -m pc_remote_bot`
   - **Start in:** `C:\path\to\pc-remote-bot`

The bot starts after you log in and keeps retrying until the network is up.

## Security

`/cmd` gives full PowerShell access to the PC. Keep `ALLOWED_USER_IDS` short, never share the
bot token, and never commit `.env` (it is in `.gitignore`).

## Development

```powershell
make check   # ruff + basedpyright + pytest
make fmt     # format and autofix
```
