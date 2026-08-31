# Revisao Ativa AFRFB

CLI simples para gerar sessoes curtas de revisao ativa (flashcards ou
questoes) a partir do seu material de estudo em PDF, para o concurso de
Auditor-Fiscal da Receita Federal do Brasil (AFRFB).

Primeira etapa do projeto: validar se a extracao do PDF e a qualidade das
revisoes geradas fazem sentido, antes de evoluir para agendamento
automatico e interface.

## Como funciona

1. Seu material fica organizado como:

   ```
   <base-dir>/<materia>/Aula<NN>.pdf
   ```

   Ex: `receita/contabilidade/Aula05.pdf`, `receita/portugues/Aula00.pdf`
   (no seu tablet, isso normalmente e algo como
   `Armazenamento interno/receita/contabilidade/Aula05.pdf`).

2. Toda semana, edite `foco-semana.md` com as 2-3 aulas de foco da semana
   e, opcionalmente, pontos de dificuldade para cada uma.

3. Ao longo da semana, rode o comando `revisar` para gerar uma sessao:

   ```bash
   python revisar.py contabilidade 05 --modo flashcard
   python revisar.py portugues 00 --modo questao
   ```

   O script localiza o PDF da aula, extrai o texto, e gera a sessao no
   formato pedido, exibida no terminal. No final, imprime uma linha clara
   avisando que a revisao esta pronta (util com o Remote Control apontado
   para o celular).

## Instalacao

```bash
pip install -r requirements.txt
```

Para gerar as sessoes com IA (recomendado), configure sua chave da API da
Claude:

```bash
export ANTHROPIC_API_KEY="sua-chave-aqui"
```

Sem chave configurada (ou com `--no-llm`), o script ainda funciona: mostra
o texto extraido do PDF e o prompt que seria enviado, o que ja e util para
validar se a extracao do PDF esta boa.

## Onde o script procura os PDFs

Por padrao, o script tenta, nesta ordem:

1. `--base-dir` passado na linha de comando
2. variavel de ambiente `AFRFB_BASE_DIR`
3. `~/storage/shared/receita` (Termux, apos `termux-setup-storage`)
4. `/storage/emulated/0/receita`
5. `./receita` (pasta local)

Se sua pasta `receita` estiver em outro lugar, aponte direto:

```bash
python revisar.py contabilidade 05 --modo flashcard --base-dir "/storage/emulated/0/receita"
```

ou defina uma vez:

```bash
export AFRFB_BASE_DIR="/storage/emulated/0/receita"
```

## Opcoes principais

| Flag | Descricao |
|---|---|
| `--modo` | `flashcard` ou `questao` (obrigatorio) |
| `--foco` | Caminho do arquivo de foco semanal (padrao: `foco-semana.md`) |
| `--base-dir` | Pasta `receita` com as materias |
| `--n` | Quantos flashcards gerar (padrao: 10) |
| `--fonte` | Para `--modo questao`: `material` (so reaproveita questao comentada do PDF), `nova` (sempre elabora questao inedita) ou `auto` (deixa o modelo escolher) |
| `--model` | Modelo da API da Claude (padrao: `claude-opus-5`) |
| `--effort` | Esforco de raciocinio: `low`, `medium` (padrao), `high`, `xhigh`, `max` |
| `--max-chars` | Limite de caracteres do PDF enviados ao modelo (padrao: 120000) |
| `--no-llm` | So extrai e mostra o texto do PDF, sem chamar a API |

## Formato do foco-semana.md

```markdown
## contabilidade

- obs: nos flashcards, evitar questoes de conta - focar em conceitos e definicoes teoricas

- Aula 05
  - dificuldades: DRE, apuracao do resultado do exercicio, CPC 26
- Aula 06

## portugues

- Aula 00
  - dificuldades: crase, regencia verbal
- Aula 03
```

Dois tipos de anotacao, ambos opcionais:

- `dificuldades:` pontos que o gerador deve **priorizar cobrir** (o modelo
  garante que pelo menos metade dos flashcards, ou a questao escolhida,
  toquem nesses pontos).
- `obs:` (aceita tambem `comentarios:`/`instrucoes:`) **instrucoes livres**
  que o gerador deve seguir a risca, tipo "evitar questoes de conta, focar
  nas teoricas" ou "prefira questoes estilo CESPE (certo/errado)".

A indentacao decide o alcance:

- Um item **indentado** sob `- Aula NN` vale so para aquela aula.
- Um item **sem indentacao**, logo apos o `## materia`, vale para a
  materia inteira (todas as aulas daquela materia usam essa instrucao).

## Proximos passos (fora do escopo desta etapa)

- Agendamento automatico (2-3x por dia)
- Interface (app/atalhos)
- Extracao especifica de trechos grifados/marcados (highlights) do PDF
