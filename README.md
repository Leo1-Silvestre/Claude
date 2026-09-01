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

Para gerar as sessoes com IA, o script usa o **Claude Code CLI** (`claude -p`)
autenticado com sua assinatura Claude (Pro/Max) - nao precisa de chave de
API paga separada:

```bash
pkg install nodejs          # se ainda nao tiver
npm install -g @anthropic-ai/claude-code
claude                      # roda uma vez, so pra fazer login com sua conta
```

Sem o CLI instalado/logado (ou com `--no-llm`), o script ainda funciona:
mostra o texto extraido do PDF e o prompt que seria enviado, o que ja e
util para validar se a extracao do PDF esta boa.

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
| `--model` | Modelo do Claude Code (padrao: o configurado na sua conta; aceita alias tipo `sonnet`, `opus`) |
| `--effort` | Esforco de raciocinio: `low`, `medium` (padrao), `high`, `xhigh`, `max` |
| `--max-chars` | Limite de caracteres do PDF enviados ao modelo (padrao: 120000) |
| `--no-llm` | So extrai e mostra o texto do PDF, sem chamar o Claude Code |

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

## Agendamento automatico (2-3x por dia)

O agendamento roda 100% no seu tablet via `cron` (Termux). O script
`agendar.py` escolhe sozinho qual aula revisar a cada execucao - ele
rotaciona pela lista de `- Aula NN` do `foco-semana.md` (round-robin) e
alterna o modo entre `flashcard` e `questao` a cada chamada. O cron so
precisa saber os horarios; a logica de "qual aula agora" fica no script.

### Configurar

```bash
pkg install python cronie nodejs   # se ainda nao tiver
pip install -r requirements.txt
npm install -g @anthropic-ai/claude-code
claude   # roda uma vez, so pra fazer login com sua conta Claude

# opcional: se sua pasta "receita" nao for detectada automaticamente, aponte pra ela num .env local:
echo 'AFRFB_BASE_DIR=/storage/emulated/0/Receita' > .env

./instalar_agendamento.sh                    # padrao: 08:00 13:00 20:00
# ou horarios customizados:
./instalar_agendamento.sh 07:30 12:00 21:30
```

O script instala o `cronie` se faltar, escreve as entradas no seu
`crontab` (sem apagar outras entradas que voce ja tenha) e inicia o
`crond`. Rodar de novo com horarios diferentes substitui os anteriores.

Para persistir depois de reiniciar o tablet, instale o app **Termux:Boot**
e crie `~/.termux/boot/start-crond.sh` com o conteudo `crond` (e
`chmod +x` nele) - sem isso, o cron para se o Termux for encerrado/o
aparelho reiniciar e precisa ser reiniciado rodando `crond` de novo.

Para notificacao no aparelho quando cada revisao terminar, instale o
app **Termux:API** e `pkg install termux-api` - o `agendar.py` detecta e
usa `termux-notification` automaticamente se disponivel; sem ele, o
agendamento continua funcionando normalmente, so sem o aviso.

### Onde ficam os resultados

- `sessoes/<data>_<materia>_aulaNN_<modo>.txt` - a integra de cada sessao gerada
- `.estado_revisao.json` - por onde a rotacao parou (nao mexa a mao, mas pode apagar para recomecar do zero)
- `sessoes/cron.log` - saida bruta de cada disparo do cron (util para depurar)

### Testar sem esperar o cron

```bash
python3 agendar.py            # roda a proxima revisao da rotacao agora
python3 agendar.py --modo flashcard   # forca o modo nesta execucao
```

## Proximos passos (fora do escopo desta etapa)

- Interface (app/atalhos)
- Extracao especifica de trechos grifados/marcados (highlights) do PDF
