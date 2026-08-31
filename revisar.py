#!/usr/bin/env python3
"""CLI de revisao ativa para o concurso AFRFB.

Uso:
    python revisar.py <materia> <aula> --modo flashcard
    python revisar.py <materia> <aula> --modo questao

Le o foco da semana em foco-semana.md, localiza o PDF da aula em
<base-dir>/<materia>/Aula<NN>.pdf, extrai o texto e gera uma sessao de
revisao (flashcards ou questao) chamando a API da Claude.

Se a API nao estiver configurada, o script ainda mostra o texto extraido
do PDF, para validar a etapa de extracao sem gastar chamadas de API.
"""

import argparse
import os
import re
import sys
import unicodedata
from pathlib import Path

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

try:
    import anthropic
except ImportError:
    anthropic = None


MODOS = ("flashcard", "questao")
DEFAULT_MODEL = os.environ.get("AFRFB_MODEL", "claude-opus-5")
DEFAULT_FOCO = "foco-semana.md"


# --------------------------------------------------------------------------
# Utilitarios
# --------------------------------------------------------------------------

def normalize(s: str) -> str:
    """minusculo, sem acento, sem espacos nas pontas - para comparar nomes."""
    s = s.strip().lower()
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def resolve_base_dir(cli_value: str | None) -> Path:
    """Descobre a pasta 'receita' (que contem uma subpasta por materia).

    Ordem de preferencia: --base-dir > env AFRFB_BASE_DIR > caminhos comuns
    de Termux/Android > ./receita local.
    """
    candidates = []
    if cli_value:
        candidates.append(Path(cli_value).expanduser())
    env_val = os.environ.get("AFRFB_BASE_DIR")
    if env_val:
        candidates.append(Path(env_val).expanduser())
    candidates += [
        Path.home() / "storage" / "shared" / "receita",
        Path("/storage/emulated/0/receita"),
        Path("./receita"),
    ]
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]


def find_materia_dir(base_dir: Path, materia: str) -> Path:
    if not base_dir.exists():
        raise FileNotFoundError(
            f"Pasta base nao encontrada: {base_dir}\n"
            "Use --base-dir para apontar para a pasta 'receita' "
            "(ex: --base-dir '/storage/emulated/0/receita') ou defina "
            "a variavel de ambiente AFRFB_BASE_DIR."
        )
    alvo = normalize(materia)
    for d in sorted(base_dir.iterdir()):
        if d.is_dir() and normalize(d.name) == alvo:
            return d
    disponiveis = sorted(d.name for d in base_dir.iterdir() if d.is_dir())
    raise FileNotFoundError(
        f"Materia '{materia}' nao encontrada em {base_dir}.\n"
        f"Pastas disponiveis: {disponiveis}"
    )


def find_aula_pdf(materia_dir: Path, aula: int) -> Path:
    candidatos = [
        f"Aula{aula:02d}.pdf",
        f"Aula{aula}.pdf",
        f"aula{aula:02d}.pdf",
        f"aula{aula}.pdf",
    ]
    for nome in candidatos:
        p = materia_dir / nome
        if p.exists():
            return p
    padrao = re.compile(rf"aula\s*0*{aula}(?!\d)", re.IGNORECASE)
    for f in sorted(materia_dir.glob("*.pdf")):
        if padrao.search(f.stem):
            return f
    disponiveis = sorted(f.name for f in materia_dir.glob("*.pdf"))
    raise FileNotFoundError(
        f"PDF da aula {aula:02d} nao encontrado em {materia_dir}.\n"
        f"Arquivos disponiveis: {disponiveis}"
    )


def extract_text(pdf_path: Path, max_chars: int) -> tuple[str, int, int, bool]:
    if PdfReader is None:
        raise RuntimeError(
            "Biblioteca 'pypdf' nao instalada. Rode: pip install -r requirements.txt"
        )
    reader = PdfReader(str(pdf_path))
    n_pages = len(reader.pages)
    partes = []
    total_len = 0
    for i, page in enumerate(reader.pages):
        texto = page.extract_text() or ""
        total_len += len(texto)
        partes.append(f"\n--- Pagina {i + 1} ---\n{texto}")
    full_text = "".join(partes)
    truncado = len(full_text) > max_chars
    if truncado:
        full_text = full_text[:max_chars] + "\n\n[...conteudo truncado pelo limite --max-chars...]"
    return full_text, n_pages, total_len, truncado


# --------------------------------------------------------------------------
# Config semanal (foco-semana.md)
# --------------------------------------------------------------------------

DIF_KEYS = {"dificuldade", "dificuldades"}
OBS_KEYS = {
    "obs", "observacao", "observacoes",
    "comentario", "comentarios",
    "instrucao", "instrucoes",
}


def _add_item(destino: dict, chave_raw: str, valor: str) -> None:
    chave = normalize(chave_raw)
    if chave in DIF_KEYS:
        itens = [d.strip() for d in valor.split(",") if d.strip()]
        destino.setdefault("dificuldades", []).extend(itens)
    elif chave in OBS_KEYS:
        # observacoes/instrucoes sao texto livre - nao quebrar por virgula
        destino.setdefault("obs", []).append(valor.strip())


def parse_foco(path: Path) -> dict:
    """Retorna { materia_normalizada: {
        "obs": [...],                                  # observacoes gerais da materia
        "aulas": { aula_num: {"dificuldades": [...], "obs": [...]} },
    }}

    Um item nao indentado logo apos "## materia" (ou apos qualquer aula) vale
    para a materia toda. Um item indentado sob "- Aula NN" vale so para essa
    aula.
    """
    foco: dict = {}
    if not path.exists():
        return foco

    materia_atual = None
    aula_atual = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        linha = raw.rstrip()
        if not linha.strip():
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        conteudo = linha.strip()

        m_materia = re.match(r"^##\s+(.+)", conteudo)
        if m_materia and indent == 0:
            materia_atual = normalize(m_materia.group(1))
            foco.setdefault(materia_atual, {"obs": [], "aulas": {}})
            aula_atual = None
            continue

        m_aula = re.match(r"^-\s*[Aa]ula\s*(\d+)", conteudo)
        if m_aula and indent == 0 and materia_atual is not None:
            aula_atual = int(m_aula.group(1))
            foco[materia_atual]["aulas"].setdefault(aula_atual, {"dificuldades": [], "obs": []})
            continue

        m_item = re.match(r"^-\s*([^:]+):\s*(.+)", conteudo)
        if m_item and materia_atual is not None:
            chave_raw, valor = m_item.group(1), m_item.group(2)
            if indent > 0 and aula_atual is not None:
                _add_item(foco[materia_atual]["aulas"][aula_atual], chave_raw, valor)
            else:
                # item nao indentado: vale para a materia toda
                _add_item(foco[materia_atual], chave_raw, valor)
            continue

    return foco


def dificuldades_para(foco: dict, materia: str, aula: int) -> list:
    m = foco.get(normalize(materia))
    if not m:
        return []
    return m.get("aulas", {}).get(aula, {}).get("dificuldades", [])


def obs_para(foco: dict, materia: str, aula: int) -> list:
    """Observacoes/instrucoes gerais da materia + especificas da aula, nessa ordem."""
    m = foco.get(normalize(materia))
    if not m:
        return []
    gerais = m.get("obs", [])
    da_aula = m.get("aulas", {}).get(aula, {}).get("obs", [])
    return gerais + da_aula


# --------------------------------------------------------------------------
# Prompts
# --------------------------------------------------------------------------

SYSTEM_PROMPT = """Voce e um professor especialista em preparar candidatos para o \
concurso de Auditor-Fiscal da Receita Federal do Brasil (AFRFB), um dos concursos \
publicos mais dificeis do Brasil. Voce recebe o texto extraido de um PDF de aula \
do material de estudo do proprio candidato (ja grifado/riscado por ele, com questoes \
comentadas e gabaritos). Seu trabalho e transformar esse material em uma sessao curta \
de revisao ativa (retrieval practice), focada no que de fato costuma ser cobrado em \
prova, e nao em teoria generica de livro-texto. Responda sempre em portugues do Brasil, \
em texto simples (sem markdown pesado), pronto para ser lido em um terminal."""


def montar_prompt_flashcard(materia, aula, texto_pdf, dificuldades, obs, n):
    partes = [
        f"Materia: {materia}",
        f"Aula: {aula:02d}",
        "",
        f"Gere exatamente {n} flashcards de conceito sobre o conteudo desta aula.",
        "Priorize os conceitos que mais aparecem sendo cobrados nas questoes "
        "comentadas dentro do proprio PDF (olhe os comentarios/gabaritos como pista "
        "do que cai em prova), nao apenas a teoria em si.",
        "Cada flashcard deve favorecer recuperacao ativa: a FRENTE deve ser uma "
        "pergunta objetiva ou uma lacuna a completar, nunca um titulo de topico. "
        "O VERSO deve ser uma resposta curta e direta (poucas linhas).",
    ]
    if dificuldades:
        partes.append(
            "O candidato indicou os seguintes pontos de dificuldade para esta aula "
            "- priorize-os, garantindo que pelo menos metade dos flashcards toque "
            "diretamente neles: " + "; ".join(dificuldades)
        )
    if obs:
        partes.append(
            "Instrucoes do candidato para esta sessao - siga-as estritamente, "
            "mesmo que isso mude a abordagem padrao (ex.: evitar um tipo de "
            "flashcard, focar em outro angulo): " + "; ".join(obs)
        )
    partes += [
        "",
        "Formato de saida (repita para cada flashcard, numerado de 1 a "
        f"{n}):",
        "N. FRENTE: <pergunta ou lacuna>",
        "   VERSO: <resposta objetiva>",
        "",
        "Nao escreva introducao nem conclusao, apenas a lista de flashcards.",
        "",
        "--- TEXTO EXTRAIDO DO PDF DA AULA ---",
        texto_pdf,
    ]
    return "\n".join(partes)


def montar_prompt_questao(materia, aula, texto_pdf, dificuldades, obs, fonte):
    partes = [
        f"Materia: {materia}",
        f"Aula: {aula:02d}",
        "",
        "Gere UMA questao de revisao no nivel e no estilo do que costuma cair na "
        "prova de AFRFB para este conteudo.",
    ]
    if fonte == "material":
        partes.append(
            "Use OBRIGATORIAMENTE uma questao ja comentada que exista dentro do "
            "texto do PDF abaixo (com enunciado, alternativas e comentario/gabarito "
            "identificaveis). Reproduza fielmente o enunciado e as alternativas, e "
            "deixe claro no topo da resposta que a questao foi 'Extraida do material'. "
            "Se voce nao conseguir identificar nenhuma questao comentada completa o "
            "suficiente no texto, diga isso claramente em vez de inventar uma."
        )
    elif fonte == "nova":
        partes.append(
            "Elabore uma questao INEDITA, no estilo e nivel de dificuldade tipicos "
            "das bancas que aplicam a prova de AFRFB, com base na teoria do PDF "
            "abaixo. Deixe claro no topo da resposta que e uma 'Questao inedita "
            "(estilo desta aula)', pois nao existe no material original."
        )
    else:
        partes.append(
            "Escolha a melhor opcao entre: (a) reaproveitar uma questao ja "
            "comentada no texto do PDF abaixo, fiel ao original, indicando "
            "claramente 'Extraida do material'; ou (b) se nao houver uma questao "
            "comentada suficientemente completa, elaborar uma questao INEDITA no "
            "estilo e nivel das bancas de AFRFB, indicando claramente 'Questao "
            "inedita (estilo desta aula)'."
        )
    if dificuldades:
        partes.append(
            "Se possivel, relacione a questao aos seguintes pontos de dificuldade "
            "indicados pelo candidato para esta aula: " + "; ".join(dificuldades)
        )
    if obs:
        partes.append(
            "Instrucoes do candidato para esta sessao - siga-as estritamente, "
            "inclusive na escolha de qual questao usar/elaborar (ex.: evitar um "
            "tipo de questao, priorizar outro estilo): " + "; ".join(obs)
        )
    partes += [
        "",
        "Formato de saida:",
        "[Extraida do material | Questao inedita (estilo desta aula)]",
        "Enunciado: <enunciado completo>",
        "a) ...",
        "b) ...",
        "c) ...",
        "d) ...",
        "e) ... (se aplicavel)",
        "",
        "--- GABARITO E COMENTARIO ---",
        "Gabarito: <letra>",
        "Comentario: <explicacao objetiva de por que a alternativa correta esta "
        "certa e as demais estao erradas>",
        "",
        "Nao escreva introducao nem conclusao, apenas a questao no formato acima.",
        "",
        "--- TEXTO EXTRAIDO DO PDF DA AULA ---",
        texto_pdf,
    ]
    return "\n".join(partes)


# --------------------------------------------------------------------------
# Chamada a API da Claude
# --------------------------------------------------------------------------

def gerar_sessao(prompt: str, model: str, effort: str) -> str | None:
    """Retorna o texto gerado, ou None se a API nao estiver disponivel/configurada."""
    if anthropic is None:
        print(
            "[aviso] pacote 'anthropic' nao instalado - mostrando apenas o texto "
            "extraido do PDF. Rode: pip install -r requirements.txt",
            file=sys.stderr,
        )
        return None

    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=model,
            max_tokens=8000,
            system=SYSTEM_PROMPT,
            thinking={"type": "adaptive"},
            output_config={"effort": effort},
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.AuthenticationError:
        print(
            "[aviso] Credenciais da API da Claude nao configuradas - mostrando "
            "apenas o texto extraido do PDF. Configure a variavel de ambiente "
            "ANTHROPIC_API_KEY (ou rode 'ant auth login').",
            file=sys.stderr,
        )
        return None
    except TypeError as e:
        # O SDK ainda nao chega a fazer a requisicao e levanta TypeError (em vez
        # de AuthenticationError) quando nao encontra nenhuma credencial no
        # ambiente (nem ANTHROPIC_API_KEY, nem perfil 'ant auth login').
        if "authentication" in str(e).lower() or "api_key" in str(e).lower():
            print(
                "[aviso] Credenciais da API da Claude nao configuradas - mostrando "
                "apenas o texto extraido do PDF. Configure a variavel de ambiente "
                "ANTHROPIC_API_KEY (ou rode 'ant auth login').",
                file=sys.stderr,
            )
            return None
        raise
    except anthropic.PermissionDeniedError:
        print("[erro] A chave de API nao tem permissao para este modelo.", file=sys.stderr)
        return None
    except anthropic.NotFoundError:
        print(f"[erro] Modelo invalido: {model}", file=sys.stderr)
        return None
    except anthropic.RateLimitError as e:
        retry_after = e.response.headers.get("retry-after", "?")
        print(f"[erro] Limite de taxa da API atingido. Tente novamente em {retry_after}s.", file=sys.stderr)
        return None
    except anthropic.APIConnectionError:
        print("[aviso] Sem conexao com a API da Claude - mostrando apenas o texto extraido do PDF.", file=sys.stderr)
        return None
    except anthropic.APIStatusError as e:
        print(f"[erro] Erro na API da Claude ({e.status_code}): {e.message}", file=sys.stderr)
        return None

    textos = [b.text for b in response.content if b.type == "text"]
    return "\n".join(textos).strip()


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="revisar",
        description="Gera uma sessao de revisao ativa (flashcards ou questao) "
        "a partir dos PDFs de aula do material de estudo para o AFRFB.",
    )
    p.add_argument("materia", help="Ex: contabilidade, portugues")
    p.add_argument("aula", help="Numero da aula, ex: 05 ou 5")
    p.add_argument("--modo", choices=MODOS, required=True, help="flashcard ou questao")
    p.add_argument("--foco", default=DEFAULT_FOCO, help=f"Arquivo de config semanal (padrao: {DEFAULT_FOCO})")
    p.add_argument("--base-dir", default=None, help="Pasta 'receita' que contem as materias (ex: /storage/emulated/0/receita)")
    p.add_argument("--n", type=int, default=10, help="Numero de flashcards a gerar (padrao: 10)")
    p.add_argument(
        "--fonte",
        choices=("material", "nova", "auto"),
        default="auto",
        help="Para --modo questao: de onde tirar a questao (padrao: auto)",
    )
    p.add_argument("--model", default=DEFAULT_MODEL, help=f"Modelo da API da Claude (padrao: {DEFAULT_MODEL})")
    p.add_argument("--effort", default="medium", choices=("low", "medium", "high", "xhigh", "max"), help="Esforco de raciocinio do modelo (padrao: medium)")
    p.add_argument("--max-chars", type=int, default=120000, help="Limite de caracteres de texto extraido enviado ao modelo")
    p.add_argument("--no-llm", action="store_true", help="Nao chama a API - so extrai e mostra o texto do PDF")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    try:
        aula = int(args.aula)
    except ValueError:
        print(f"[erro] Numero de aula invalido: {args.aula!r}", file=sys.stderr)
        return 1

    base_dir = resolve_base_dir(args.base_dir)

    try:
        materia_dir = find_materia_dir(base_dir, args.materia)
        pdf_path = find_aula_pdf(materia_dir, aula)
    except FileNotFoundError as e:
        print(f"[erro] {e}", file=sys.stderr)
        return 1

    print(f"[info] PDF localizado: {pdf_path}", file=sys.stderr)

    try:
        texto_pdf, n_pages, total_len, truncado = extract_text(pdf_path, args.max_chars)
    except RuntimeError as e:
        print(f"[erro] {e}", file=sys.stderr)
        return 1

    media_por_pagina = total_len / n_pages if n_pages else 0
    print(f"[info] {n_pages} paginas, {total_len} caracteres extraidos ({media_por_pagina:.0f}/pagina).", file=sys.stderr)
    if media_por_pagina < 50:
        print(
            "[aviso] Pouco texto extraido por pagina - o PDF pode ser escaneado "
            "(imagem) em vez de texto pesquisavel. Considere rodar OCR antes.",
            file=sys.stderr,
        )
    if truncado:
        print(f"[aviso] Texto truncado em {args.max_chars} caracteres (use --max-chars para ajustar).", file=sys.stderr)

    foco = parse_foco(Path(args.foco))
    dificuldades = dificuldades_para(foco, args.materia, aula)
    obs = obs_para(foco, args.materia, aula)
    if dificuldades:
        print(f"[info] Dificuldades apontadas em {args.foco}: {'; '.join(dificuldades)}", file=sys.stderr)
    if obs:
        print(f"[info] Instrucoes apontadas em {args.foco}: {'; '.join(obs)}", file=sys.stderr)

    if args.modo == "flashcard":
        prompt = montar_prompt_flashcard(args.materia, aula, texto_pdf, dificuldades, obs, args.n)
    else:
        prompt = montar_prompt_questao(args.materia, aula, texto_pdf, dificuldades, obs, args.fonte)

    resultado = None if args.no_llm else gerar_sessao(prompt, args.model, args.effort)

    print()
    print("=" * 70)
    print(f"REVISAO - {args.materia.upper()} - Aula {aula:02d} - modo: {args.modo}")
    print("=" * 70)
    print()

    if resultado is not None:
        print(resultado)
    else:
        print(
            "[modo sem LLM] Nenhuma sessao foi gerada por IA. Abaixo esta o "
            "texto extraido do PDF e o prompt que seria enviado, para validar "
            "a extracao manualmente ou colar em outra conversa com a Claude.\n"
        )
        print("--- PROMPT ---")
        print(prompt)

    print()
    print("=" * 70)
    print(f">>> Revisao de {args.materia} Aula {aula:02d} ({args.modo}) pronta.")
    print("=" * 70)

    return 0


if __name__ == "__main__":
    sys.exit(main())
