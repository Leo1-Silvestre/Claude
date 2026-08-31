#!/usr/bin/env bash
# Configura o agendamento automatico (cron) da revisao AFRFB no Termux.
#
# Uso:
#   ./instalar_agendamento.sh                  # usa 08:00 13:00 20:00
#   ./instalar_agendamento.sh 07:30 12:00 21:00 # horarios customizados
#
# Reexecutar com horarios diferentes substitui os anteriores (idempotente).

set -euo pipefail

HORARIOS=("$@")
if [ ${#HORARIOS[@]} -eq 0 ]; then
  HORARIOS=("08:00" "13:00" "20:00")
fi

DIR_PROJETO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MARCADOR="# revisar-afrfb-agendamento"

echo "Projeto: $DIR_PROJETO"

if ! command -v crond >/dev/null 2>&1 && ! command -v cron >/dev/null 2>&1; then
  if command -v pkg >/dev/null 2>&1; then
    echo "cron nao encontrado - instalando cronie (Termux)..."
    pkg install -y cronie
  else
    echo "cron/crond nao encontrado e 'pkg' nao disponivel (isto nao parece ser o Termux)."
    echo "Instale o cron do seu sistema e rode este script novamente."
    exit 1
  fi
fi

mkdir -p "$DIR_PROJETO/sessoes"

CRON_ATUAL="$(crontab -l 2>/dev/null || true)"
CRON_SEM_MARCADOR="$(printf '%s\n' "$CRON_ATUAL" | grep -v -F "$MARCADOR" || true)"

NOVAS_LINHAS=""
for HORA in "${HORARIOS[@]}"; do
  HH="${HORA%%:*}"
  MIN="${HORA#*:}"
  NOVAS_LINHAS+="${MIN} ${HH} * * * cd \"$DIR_PROJETO\" && python3 agendar.py >> \"$DIR_PROJETO/sessoes/cron.log\" 2>&1 $MARCADOR"$'\n'
done

{ printf '%s\n' "$CRON_SEM_MARCADOR"; printf '%s' "$NOVAS_LINHAS"; } | crontab -

echo "Crontab atualizado com os horarios: ${HORARIOS[*]}"

if command -v sv-enable >/dev/null 2>&1; then
  sv-enable crond >/dev/null 2>&1 || true
  echo "crond habilitado via termux-services (sobrevive a app fechado, mas nao a reboot sem Termux:Boot)."
else
  crond >/dev/null 2>&1 || true
  echo "crond iniciado manualmente. Ele para se o Termux for totalmente encerrado/reiniciado o aparelho."
fi

cat <<EOF

Pronto. Proximos passos:

1. Confira: crontab -l
2. Rode uma vez na mao para testar: python3 agendar.py
3. Para o agendamento sobreviver a reinicio do tablet, instale o app
   "Termux:Boot" (F-Droid/Play Store) e crie ~/.termux/boot/start-crond.sh
   com o conteudo:  crond
   (e de permissao de execucao: chmod +x ~/.termux/boot/start-crond.sh)
4. Notificacoes no aparelho: instale o app "Termux:API" e o pacote
   'pkg install termux-api' para receber um aviso quando cada revisao
   estiver pronta.

Logs de cada execucao ficam em: $DIR_PROJETO/sessoes/
EOF
