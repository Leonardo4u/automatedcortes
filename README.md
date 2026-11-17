# corte-react

Skill para o [Claude Code](https://claude.com/claude-code) que transforma lives e VODs em cortes verticais (TikTok, Reels, Shorts) no formato **react**: a webcam de quem reage em cima e o conteúdo embaixo.

Você coloca o vídeo numa pasta, pede "faz os cortes", e ela:

1. **Acha os melhores momentos** — mede o volume do áudio do vídeo inteiro, pega os picos de agitação repartidos por hora e analisa um trecho em volta de cada um.
2. **Monta o corte** em 1080x1920: webcam em cima, vídeo/jogo/chat embaixo, com os recortes medidos em cada trecho.
3. **Põe uma placa de CTA animada** sobre a divisa nos 3 primeiros segundos.
4. **Legenda** lives de conversa e reacts no estilo "palavra que acende": três palavras por vez, a palavra falada em amarelo.
5. **Sugere a descrição** de cada corte, com chamada para ação e hashtags, num `descricoes.txt`.

## Requisitos

- **Claude Code** (app de desktop, terminal ou extensão).
- **Python 3.10+** — os scripts só usam a biblioteca padrão.
- **ffmpeg 8 ou mais novo, compilado com o filtro `whisper`** (e `ffprobe`). Confira com:

  ```bash
  ffmpeg -hide_banner -h filter=whisper
  ```

  No Windows, o build "full" do Gyan já vem com ele: `winget install Gyan.FFmpeg`.
- **Um modelo do Whisper** em formato ggml, para a transcrição local (legendas e análise de reserva). Baixe o `ggml-large-v3-turbo.bin` (1,6 GB) de <https://huggingface.co/ggerganov/whisper.cpp> e salve em `~/.cache/corte-react/`.

### Opcional: análise com o Gemini

Com a skill [`watch`](https://github.com/bradautomates/claude-video) instalada e uma chave de API do Gemini configurada, a busca de momentos manda uma compilação dos trechos para o Gemini, que vê e ouve o vídeo e devolve nota, início e fim de cada corte. É o caminho que mais acerta, principalmente em momentos visuais.

Sem ela, ou quando o Gemini está sobrecarregado ou sem cota (a chave gratuita tem limite diário baixo), a skill cai sozinha para a reserva local: transcreve os trechos com o Whisper e o Claude dá as notas pelo texto. Nada sai do computador nesse modo.

## Instalação

Clone direto na pasta de skills do Claude Code:

```bash
git clone https://github.com/Leonardo4u/automatedcortes.git ~/.claude/skills/corte-react
```

A pasta de destino precisa se chamar `corte-react`, que é o nome da skill, mesmo o repositório tendo outro nome.

Abra uma sessão nova do Claude Code. No primeiro uso a skill pergunta onde ficam as suas duas pastas (a de entrada, com os VODs, e a de saída, com os cortes prontos) e grava a resposta em `pastas.json`. Se preferir, copie `pastas.exemplo.json` para `pastas.json` e edite na mão.

## Uso

Coloque o vídeo na pasta de entrada e peça:

```text
/corte-react faz os cortes
```

Você pode dar mais detalhes na mesma mensagem:

- **Trechos:** "corta de 12:30 a 13:10" — pula a busca automática.
- **Quantidade:** "só os 5 melhores".
- **Canal e plataforma:** "é live do Fulano na Kick" — acerta as hashtags.
- **Privacidade:** "não manda pro Google" — usa só a análise local.

Cada vídeo ganha uma subpasta na pasta de saída, com os clipes numerados e o `descricoes.txt`.

## Os scripts

Dá para usar os scripts sem o Claude:

| Script | O que faz |
|---|---|
| `scripts/momentos.py` | Acha os picos de agitação, extrai os trechos e pede a análise (Gemini ou transcrição local) |
| `scripts/react.py` | Monta o corte: `frame` (quadro com grade para medir recortes), `preview` (um quadro do resultado) e `render` |
| `scripts/classico.py` | Formato clássico para quem fala em tela cheia: vídeo 16:9 no meio, fundo desfocado, título fixo em cima e legenda embaixo (`preview` e `render`) |
| `scripts/legenda.py` | Transcreve o trecho palavra por palavra e gera a legenda `.ass` para o `react.py` ou o `classico.py` gravar |

Cada um aceita `--help`.

## Limites conhecidos

- A busca só enxerga momentos barulhentos. Um trecho bom falado em tom normal passa despercebido; nesse caso indique o tempo.
- Em gameplay com várias pessoas falando ao mesmo tempo a transcrição embaralha as falas, por isso esses cortes saem sem legenda.
- A transcrição erra nomes próprios e gíria. A skill revisa o texto antes de gravar a legenda, mas vale conferir.
- Testada no Windows 10 com ffmpeg 9. Os scripts não têm nada específico de Windows, mas macOS e Linux não foram testados.

## Sobre o conteúdo dos cortes

A skill é uma ferramenta de edição. Lives e vídeos de outros criadores têm dono: antes de publicar um corte, confira se você tem permissão e o que as regras da plataforma dizem.
