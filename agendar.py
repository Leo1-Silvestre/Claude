#!/usr/bin/env python3
"""Agendador da revisao ativa AFRFB.

Nao decide horarios (isso fica a cargo do cron/crond - veja
instalar_agendamento.sh). Cada vez que este script roda, ele:

1. Le foco-semana.md e pega a lista de (materia, aula) da semana.
2. Escolhe o proximo item por rotacao (round-robin), guardando o estado
   em .estado_revisao.json, e alterna o modo (flashcard/questao).
3. Chama revisar.py para esse item.
4. Salva a saida em sessoes/<data>_<materia>_aulaNN_<modo>.txt.
5. Dispara uma notificacao Android via `termux-notification`, se
   disponivel (pacote Termux:API).

Pensado para ser chamado 2-3x por dia via cron, sem argumentos.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import revisar  # noqa: E402  (reusa normalize())

BASE_DIR_SCRIPT = Path(__file__).resolve().parent
ESTADO_PATH = BASE_DIR_SCRIPT / ".estado_revisao.json"
LOGS_DIR = BASE_DIR_SCRIPT / "sessoes"
ENV_PATH = BASE_DIR_SCRIPT / ".env"
MODOS_ALTERNANCIA = ("flashcard", "questao")


def carregar_env() -> None:
    """Le .env (KEY=VALUE por linha) se existir, sem sobrescrever env ja definido.

    Cron roda com ambiente minimo - isso evita ter que colocar
    AFRFB_BASE_DIR etc. dentro do crontab.
    """
    if not ENV_PATH.exists():
        return
    for raw in ENV_PATH.read_text(encoding="utf-8").splitlines():
        linha = raw.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        chave = chave.strip()
        valor = valor.strip().strip('"').strip("'")
        os.environ.setdefault(chave, valor)


def listar_itens_foco(foco_path: Path) -> list:
    """Retorna [(materia_como_escrita_no_arquivo, aula), ...] na ordem do arquivo.

    So considera "## materia" e "- Aula NN" sem indentacao (mesma regra de
    escopo usada em revisar.parse_foco).
    """
    if not foco_path.exists():
        return []
    itens = []
    materia_atual = None
    for raw in foco_path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        conteudo = raw.strip()

        m_materia = re.match(r"^##\s+(.+)", conteudo)
        if m_materia and indent == 0:
            materia_atual = m_materia.group(1).strip()
            continue

        m_aula = re.match(r"^-\s*[Aa]ula\s*(\d+)", conteudo)
        if m_aula and indent == 0 and materia_atual is not None:
            itens.append((materia_atual, int(m_aula.group(1))))

    return itens


def carregar_estado() -> dict:
    if ESTADO_PATH.exists():
        try:
            return json.loads(ESTADO_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"indice": -1, "execucoes": 0}


def salvar_estado(estado: dict) -> None:
    ESTADO_PATH.write_text(json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8")


def notificar(titulo: str, conteudo: str) -> None:
    if shutil.which("termux-notification") is None:
        return
    subprocess.run(
        ["termux-notification", "--title", titulo, "--content", conteudo],
        check=False,
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="agendar",
        description="Roda automaticamente a proxima revisao da semana (rotaciona "
        "entre as aulas de foco-semana.md). Pensado para ser chamado pelo cron.",
    )
    p.add_argument("--foco", default=str(BASE_DIR_SCRIPT / "foco-semana.md"))
    p.add_argument(
        "--modo",
        choices=MODOS_ALTERNANCIA,
        default=None,
        help="Forca um modo especifico (padrao: alterna flashcard/questao a cada execucao)",
    )
    return p


def main(argv=None) -> int:
    p = build_parser()
    args, resto = p.parse_known_args(argv)

    carregar_env()

    foco_path = Path(args.foco)
    itens = listar_itens_foco(foco_path)
    if not itens:
        print(
            f"[erro] Nenhuma aula de foco encontrada em {foco_path}. "
            "Edite o arquivo com as aulas da semana antes de agendar.",
            file=sys.stderr,
        )
        return 1

    estado = carregar_estado()
    estado["indice"] = (estado["indice"] + 1) % len(itens)
    materia, aula = itens[estado["indice"]]

    modo = args.modo or MODOS_ALTERNANCIA[estado["execucoes"] % len(MODOS_ALTERNANCIA)]

    LOGS_DIR.mkdir(exist_ok=True)
    agora = datetime.now()
    log_path = LOGS_DIR / f"{agora:%Y-%m-%d_%H%M}_{revisar.normalize(materia)}_aula{aula:02d}_{modo}.txt"

    cmd = [
        sys.executable,
        str(BASE_DIR_SCRIPT / "revisar.py"),
        materia,
        str(aula),
        "--modo",
        modo,
        "--foco",
        str(foco_path),
        *resto,
    ]
    resultado = subprocess.run(cmd, capture_output=True, text=True)
    log_path.write_text(resultado.stdout + "\n" + resultado.stderr, encoding="utf-8")

    print(resultado.stdout)
    if resultado.stderr:
        print(resultado.stderr, file=sys.stderr)

    if resultado.returncode == 0:
        estado["execucoes"] += 1
        salvar_estado(estado)
        notificar(
            f"Revisao pronta: {materia} Aula {aula:02d}",
            f"Modo: {modo} - log: {log_path.name}",
        )
    else:
        print(
            f"[erro] revisar.py falhou (codigo {resultado.returncode}) - estado nao "
            "avancado, a proxima execucao tenta o mesmo item de novo.",
            file=sys.stderr,
        )

    return resultado.returncode


if __name__ == "__main__":
    sys.exit(main())
