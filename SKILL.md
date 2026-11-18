---
name: corte-react
description: Monta vídeos verticais (TikTok, Reels, Shorts) no formato react — câmera/reação em cima e o vídeo assistido embaixo, 1080x1920. Use sempre que o usuário pedir um corte de react, corte de live ou de streamer, vídeo com "câmera em cima e vídeo embaixo", tela dividida vertical, facecam em cima de gameplay, ou quiser transformar um clipe de live (Kick, Twitch, YouTube) ou dois arquivos (reação + conteúdo) nesse layout, mesmo que não diga a palavra "react". Trechos em que a pessoa só fala em tela cheia (vlog, podcast, live de conversa sem nada na tela) saem no formato clássico: vídeo no meio, título em cima, legenda embaixo. Também acha sozinho os melhores momentos de um VOD ou live longa: use quando o usuário disser que baixou um vídeo e pedir "faz cortes", "cria clipes" ou "acha os melhores momentos", sem indicar trechos. Entrega cada corte com placa de CTA, descrição e hashtags.
allowed-tools: Bash, Read, AskUserQuestion
---

# corte-react

Monta o formato de corte de streamer: a **câmera de quem reage em cima** e o **conteúdo assistido embaixo**, num vertical de 1080x1920 a 30 fps. Todo o trabalho pesado é do script `scripts/react.py` (Python padrão + ffmpeg); o seu papel é descobrir as regiões certas do quadro, conferir a prévia com os próprios olhos e só então renderizar. Para quem fala em tela cheia, sem conteúdo para pôr embaixo, existe o formato clássico (`scripts/classico.py`, veja "Formato clássico").

`SKILL_DIR` é a pasta deste SKILL.md. No Windows use `python`; no macOS/Linux, `python3`.

## Pastas do usuário

O usuário trabalha com duas pastas fixas, gravadas no arquivo `pastas.json` ao lado deste SKILL.md:

```json
{
  "entrada": "C:/Users/voce/Desktop/Cortes/VODs",
  "saida": "C:/Users/voce/Desktop/Cortes/Prontos"
}
```

- **`entrada`** — onde ele coloca o VOD ou vídeo a cortar.
- **`saida`** — onde os cortes prontos devem ficar. Nas instruções abaixo ela aparece como `Prontos`.

Leia `pastas.json` no começo de cada uso. Se o arquivo não existir (instalação nova), pergunte ao usuário uma única vez onde ele quer as duas pastas, ofereça criar `Cortes/VODs` e `Cortes/Prontos` na Área de Trabalho, crie as pastas e grave o arquivo. Esse arquivo é pessoal: não vai para o repositório (está no `.gitignore`).

Como usar:

- Se ele pedir cortes sem dizer qual vídeo ("faz os cortes", "tem vídeo novo"), procure na pasta de entrada. Um vídeo já foi processado quando existe em `Prontos` uma subpasta com o nome dele; trabalhe nos que ainda não têm. Havendo mais de um pendente, faça um por vez, do mais antigo ao mais novo, e diga a ordem.
- Salve os cortes de cada vídeo em `Prontos\<nome do vídeo sem extensão>\`, junto com o `descricoes.txt`. Uma subpasta por vídeo evita misturar clipes de lives diferentes e é o que marca o vídeo como feito.
- Se ele indicar um vídeo em outro lugar, use esse vídeo onde está, mas a saída continua indo para `Prontos`, salvo se ele disser outra pasta.
- Não mova, renomeie nem apague o vídeo de entrada: são arquivos grandes dele. Se a pasta de entrada encher, avise e deixe a limpeza com ele.
- As pastas de trabalho (trechos, transcrições, prévias) continuam na pasta temporária, nunca dentro de `Cortes`.

Se uma das duas pastas não existir, avise o usuário em vez de criar outra em silêncio: ele pode tê-la movido.

## O layout

Medido em cortes reais desse formato:

- Saída 1080x1920, 30 fps, H.264 + AAC.
- Topo: câmera em 16:9 ocupando a largura toda (1080x608, cerca de 32% da altura). O rosto precisa estar inteiro e mais ou menos centrado.
- Embaixo: o conteúdo nos 1312 px restantes, cortado para preencher (`cover`).
- Opcional: uma marca d'água de texto bem na divisa (por exemplo o canal do streamer).

`--split` muda a proporção (0.30 a 0.37 é a faixa vista nos cortes de referência). Não há legenda queimada: esses cortes normalmente não têm.

## Dois pontos de partida

**Um arquivo só (o caso comum).** Um clipe de live em que a webcam e o conteúdo aparecem no mesmo quadro. Você recorta as duas regiões do mesmo vídeo; o áudio já vem sincronizado.

**Dois arquivos.** A gravação da câmera e o vídeo assistido vêm separados. Aqui o sincronismo é responsabilidade do usuário: pergunte em que instante cada um começa (`--start` para o conteúdo, `--cam-start` para a câmera) se não estiver claro.

## Formato clássico (quem fala em tela cheia)

Quando o trecho é só a pessoa falando para a câmera em tela cheia, não há o que pôr embaixo. O usuário aprovou este formato para esses casos:

- o quadro 16:9 levemente ampliado (`--zoom 1.185`: corta ~8% de cada lateral) ocupando a largura toda no meio, de y=600 a y=1320;
- o mesmo vídeo desfocado e escurecido preenchendo o fundo;
- uma placa amarela fixa, levemente inclinada, em cima (o título, quebrado sozinho em até duas linhas, com número grudado na palavra: "GTA 6" nunca vira "GTA / 6");
- a legenda com a palavra que acende logo abaixo do vídeo.

Ele mostra o quadro inteiro, então serve mesmo quando a pessoa se mexe de um lado para o outro (o que estraga um recorte vertical fixo do rosto). Como é conversa, leva legenda.

```bash
python "${SKILL_DIR}/scripts/legenda.py" "<video>" --start 1110 --end 1140 --split 0.75 --depois-de 0 --out "<pasta-temp>/c01.ass"
python "${SKILL_DIR}/scripts/classico.py" preview --source "<video>" --start 1110 --end 1140 \
  --subs "<pasta-temp>/c01.ass" --title "O dia que o GTA 6 foi anunciado" --at 9 --out "<pasta-temp>/previa.jpg"
python "${SKILL_DIR}/scripts/classico.py" render --source "<video>" --start 1110 --end 1140 \
  --subs "<pasta-temp>/c01.ass" --title "O dia que o GTA 6 foi anunciado" --out "<Prontos>/<video>/01_nome.mp4"
```

- Na legenda, use sempre `--split 0.75` (fica centrada a 1440 px, logo abaixo do vídeo) e `--depois-de 0` (aqui o título é fixo, não há placa animada para esperar). A revisão das palavras é a mesma do passo 3.
- O título é o gancho do corte, curto (até umas 7 palavras), escrito por você; diga ao usuário qual usou.
- As regras de "Os 3 primeiros segundos" (primeira frase no assunto do título, rosto no primeiro quadro) valem aqui também: confira com `preview --at 0` e `--at 1`.
- Se o rosto ficar perto de uma borda o trecho todo, `--shift` desloca o corte das laterais (-1 a 1); `--zoom 1.0` mostra o quadro inteiro, sem cortar nada.
- Num vídeo que mistura formatos (compilação, live que alterna tela cheia e jogo), decida corte a corte: webcam pequena sobre conteúdo vai para o `react.py`; pessoa em tela cheia vai para o clássico.

## Fluxo

### 0. Ache os momentos (quando o usuário não disse os trechos)

O caso normal é o usuário baixar um vídeo longo (live, VOD), dizer onde está e pedir cortes, sem indicar trechos. Não pergunte quais: procure.

```bash
python "${SKILL_DIR}/scripts/momentos.py" "<video>" --out-dir "<pasta-temp>/busca"
```

Rode em segundo plano: num VOD de horas, medir o áudio leva alguns minutos e a análise mais alguns. O script mede o volume segundo a segundo, escolhe os picos de agitação (riso, grito, comemoração), extrai 80 segundos em volta de cada um, cola todos numa compilação rotulada ("TRECHO N") e faz **um único pedido** ao Gemini pela skill `watch`. Devolve, por candidato, nota, início e fim do corte (em segundos do vídeo original), o canto da webcam, um título e uma frase de descrição. A saída é uma tabela, com tudo também em `momentos.json`.

- Os marcados `OK` têm nota igual ou maior que `--min-nota` (padrão 7). Faça cortes de todos eles, salvo se o usuário pediu uma quantidade; `--top N` muda quantos picos são analisados (padrão 14).
- Os candidatos são repartidos por hora do vídeo, para a parte mais barulhenta da live não levar todos. Num VOD de mais de 3 horas, ou quando o usuário quer muitos cortes, use `--top 30`: com 14 sobra pouco por hora e a busca rende 2 ou 3 clipes. Acima de 15 trechos o Gemini é chamado em lotes (um pedido a cada 15).
- Se o resultado vier magro, não entregue só o que passou: diga quantos candidatos foram analisados e ofereça baixar a nota mínima para 6 ou analisar mais picos.
- Momentos em que a webcam ocupa a tela inteira (só conversa) não têm "vídeo embaixo" e não servem para o layout react: faça-os no formato clássico (veja "Formato clássico"), não os descarte. Descarte só o que não tem rosto nem conteúdo que se sustente sozinho (um menu parado, uma tela de carregamento) e diga ao usuário quais foram.
- Cada aprovado ganha uma `grade_NN.jpg`: três quadros do trecho (início, meio, fim) com a grade de 10x10. Abra cada uma para definir os recortes — ela substitui o passo 1 para esses clipes, e mostra se a webcam muda de lugar ou some durante o trecho. Se a webcam sumir porque o streamer foi para tela cheia, o trecho vai para o formato clássico; se sumir porque trocou de cena e não sobrou rosto nem conteúdo útil, descarte o candidato e diga ao usuário por quê. Em vídeos editados (compilações, vídeos de YouTube) a cena muda a cada poucos segundos e três quadros enganam: monte uma folha com 9 quadros do trecho (`ffmpeg -ss INICIO -t DUR -i VIDEO -vf "fps=9/DUR,scale=320:-1,drawgrid=w=32:h=18:c=yellow@0.5,tile=3x3" -frames:v 1 folha.jpg`) e confira também onde começa cada segmento, para o corte não abrir no meio de uma transição.
- Leia `analise.md` (a resposta inteira do Gemini): é dela que saem o texto da placa de CTA e a descrição da postagem. Se a tabela avisar que algum trecho ficou "sem nota legível", a análise dele costuma estar lá, só fora do formato; leia e decida.
- O título e a nota são opinião do Gemini sobre um trecho curto, não fato verificado. Diga isso ao usuário ao apresentar os cortes.

**Os 3 primeiros segundos decidem o corte.** Nas métricas dos cortes já postados, a maior parte do público sai entre o segundo 1 e o 3; depois disso a queda é lenta. Por isso o início que o Gemini (ou você, na reserva local) escolheu é só um ponto de partida. Antes de renderizar, ajuste o `--start` de cada corte por estas duas regras:

1. **A primeira frase entra no assunto da placa.** Ela precisa citar ou armar diretamente aquilo que a placa de CTA promete. Pule muletas e retomadas ("então", "assim", "tipo", "já falei isso", "como eu tava dizendo") e frases que começam pela metade. Exemplo real: o corte que abria com "Los Santos é…" sob a placa "ELE CHUTOU MIAMI PRO GTA 6" segurou 66% do público aos 3 segundos; o que abria com "que é importante pra nós assim" perdeu 57% em 2 segundos. Confira lendo as primeiras falas do trecho (a primeira linha que o `legenda.py` lista, ou `transcricoes.md`); se a frase boa vier alguns segundos depois, avance o `--start` até ela, mesmo que o corte fique mais curto.
2. **O primeiro quadro tem rosto.** Nada de abrir em vinheta, tela colorida, transição ou cena de carregamento do vídeo original: o corte que começava com 1 segundo de tela amarela antes de aparecer a pessoa foi um dos que mais perderam gente no começo. A verificação está nos passos 3 e 5.

**Cota do Gemini.** A chave gratuita do usuário permite poucos pedidos por dia (20, na última vez em que o limite apareceu), e é por isso que a busca usa um só por vídeo. Não chame a skill `watch` trecho por trecho para "conferir" candidatos: cada chamada gasta um pedido. Se a tabela avisar que a cota acabou, diga ao usuário quando ela volta e a reserva local entra sozinha; siga por ela em vez de deixar o usuário esperando, e avise que rodar o mesmo comando mais tarde refaz a análise pelo Gemini (o áudio e os trechos ficam guardados na pasta de trabalho, então a segunda rodada é rápida). A assinatura do aplicativo Gemini não aumenta a cota da chave de API; são coisas separadas.

**Reserva local, quando o Gemini falha.** O Gemini gratuito fica sobrecarregado com frequência (erro 503) e a cota acaba. Nesses casos o script não para: transcreve os trechos nesta máquina com o Whisper embutido no ffmpeg (modelo em `~/.cache/corte-react/`, cerca de 4 minutos para 14 trechos) e a tabela sai com `modo: transcricao` e o aviso `RESERVA LOCAL`. Aí a nota é sua:

1. Leia `transcricoes.md` inteiro (é curto). Cada trecho traz as falas com o tempo contado do início do trecho e o instante do pico de áudio.
2. Dê a cada trecho uma nota de 0 a 10 com o mesmo critério do Gemini: existe um momento engraçado, surpreendente ou marcante que funcione sozinho? Conversa comum vale 4 ou menos. Gritos repetidos logo depois de uma fala forte ("Caralho! Caralho!", "Vamos! Vencemos!") costumam ser a reação do streamer, e reação é o que faz um corte de react.
3. Para os de nota 7 ou mais, escolha início e fim (15 a 50 segundos): comece na primeira frase que já entra no assunto (veja "Os 3 primeiros segundos") e termine depois da reação. Some o "início do trecho" para obter os segundos do vídeo original.
4. Gere as folhas de quadros só dos escolhidos e siga para o passo 2:

```bash
python "${SKILL_DIR}/scripts/momentos.py" "<video>" --out-dir "<pasta-temp>/busca" --grades "6:4790:4818,7:6612:6658"
```

Diga ao usuário que a seleção veio da transcrição, não do Gemini: você leu as palavras, mas não ouviu o tom nem viu a cena em movimento, então a escolha é um pouco menos segura. A transcrição erra nomes próprios e gíria; não copie um nome dela para a placa de CTA ou para a descrição sem ele aparecer de forma consistente ou o usuário confirmar. `--local` vai direto para a reserva sem tentar o Gemini.

**Privacidade.** Os trechos vão para o Google. Se o usuário disser que o vídeo não pode sair da máquina, ou se a skill `watch` não estiver instalada com o Gemini, use `--local`: nada sai do computador e você dá as notas pela transcrição, como descrito acima. Sem o modelo do Whisper instalado, resta `--no-gemini`: os momentos saem só do volume do áudio (20 segundos antes até 12 depois de cada pico), sem nota nem título; avise que a seleção fica bem mais fraca.

O método só enxerga barulho. Um momento bom falado em tom normal passa despercebido; se o usuário souber de algum, ele indica o trecho e você pula direto para o passo 1.

### 1. Olhe o quadro antes de recortar

```bash
python "${SKILL_DIR}/scripts/react.py" frame "<video>" --at 5 --grid --out "<pasta-temp>/quadro.jpg"
```

O comando informa a resolução, a duração e se há áudio. Abra a imagem com a ferramenta de leitura de imagens. A grade amarela tem 10 colunas e 10 linhas: cada linha marca 0.1 do quadro, o que permite ler as regiões direto em frações.

Confira mais de um instante (`--at`) quando o vídeo for longo: overlays, alertas e a posição da webcam mudam durante uma live, e um recorte que serve no segundo 5 pode cortar a cabeça do streamer no minuto 3.

### 2. Defina as regiões

Os recortes são `x,y,largura,altura`, em pixels ou em frações de 0 a 1 (quando os quatro valores são ≤ 1, o script trata como fração). Frações são mais fáceis de ler na grade.

- **Câmera (`--cam-crop`)**: enquadre a webcam com folga acima da cabeça. Prefira uma região próxima de 16:9; se não for, o script corta o excesso pelo centro.
- **Conteúdo (`--content-crop`)**: enquadre só o que interessa — o player do vídeo, o jogo — deixando de fora chat, barra do navegador e a própria webcam. A área de destino é mais alta do que larga (1080x1312, cerca de 5:6), então um conteúdo em 16:9 perde as laterais em `cover`. Se as laterais importam (texto, placar, legenda), use `--fit contain`, que mostra o conteúdo inteiro sobre uma cópia desfocada.

No modo de dois arquivos os recortes são opcionais: sem eles, cada vídeo é usado inteiro.

### 3. Confira a prévia

```bash
python "${SKILL_DIR}/scripts/react.py" preview --source "<video>" \
  --cam-crop "0.70,0.62,0.30,0.30" --content-crop "0.05,0.08,0.62,0.80" \
  --start 12 --at 3 --out "<pasta-temp>/previa.jpg"
```

**Espaço vazio e título.** No modo `contain` sobra uma faixa desfocada entre a câmera e o vídeo; a prévia avisa quantos pixels. Esse vazio fica com cara de erro, então cubra-o com `--title "TEXTO"`: um título curto em estilo de chamada (o gancho do corte, não uma descrição), que o script põe em maiúsculas, quebra em até três linhas e dimensiona para caber na faixa. Com título, o vídeo desce até a base do quadro e o título ocupa todo o espaço que sobraria, para não ficar outra faixa vazia embaixo. Escreva você mesmo o título a partir do que acontece no trecho e diga ao usuário qual usou, para ele poder trocar. No modo `cover` não há vazio; `--title` ainda funciona, como uma faixa sobre o topo do conteúdo, mas só use se o usuário pedir.

**Placa de CTA animada (o layout preferido do usuário).** `--split 0.5 --cta "TEXTO"` divide o quadro meio a meio e põe uma placa amarela inclinada sobre a divisa, que entra deslizando, fica `--cta-duration` segundos (padrão 3) e some, deixando só a webcam e o vídeo. Com metade do quadro para cada parte, o conteúdo em 16:9 quase não perde laterais em `cover`, então não sobra espaço vazio depois que a placa sai. A câmera fica mais fechada no rosto (perde as laterais). Na prévia, use `--at` menor que a duração da placa para vê-la.

**Legenda com a palavra que acende (padrão do usuário).** Levam legenda os cortes de lives de conversa (uma pessoa falando, e o corte é o que ela diz) e de reacts (o streamer comentando o que vê). Ela mostra até três palavras por vez sobre a divisa, no lugar da placa de CTA e só depois que a placa sai; a palavra falada fica amarela e cresce para 122%. O usuário aprovou exatamente esse estilo e o sincronismo — não mude tamanho, cor, crescimento nem posição por conta própria (ele testou um "quique" e um crescimento menor e recusou os dois).

```bash
python "${SKILL_DIR}/scripts/legenda.py" "<video>" --start 8266 --end 8314 --split 0.36 --out "<pasta-temp>/corte02.ass"
```

Use o mesmo `--start`, `--end` e `--split` do corte. O comando lista os blocos de texto: leia todos antes de renderizar, porque um erro de transcrição gravado no vídeo não tem conserto depois. Corrija palavras erradas (nomes, gíria, "deu gris" no lugar de "deu green") direto no `.palavras.tsv` que ele grava ao lado, sem mexer nos tempos, e refaça com `--from-palavras <arquivo.tsv>` e as mesmas opções. Depois passe `--subs <arquivo.ass>` ao `preview` e ao `render`. Diga ao usuário quais palavras corrigiu e quais ficou em dúvida.

**Gameplay não leva legenda.** O usuário decidiu: legenda só em lives de conversa e em reacts. Em gameplay, com várias pessoas falando e gritando ao mesmo tempo, a transcrição embaralha as falas e polui a tela, então esses cortes saem só com a placa de CTA. Não legende um corte de gameplay por achar que aquele diálogo ficou limpo; se parecer que vale, sugira ao usuário e deixe ele decidir. Numa live que mistura os tipos (react no começo, gameplay depois), decida corte a corte pelo que está na tela naquele trecho.

Gere também uma prévia com `--at 0` e outra com `--at 1` (vale para o `react.py` e para o `classico.py`) e confirme que já há rosto na tela nos dois instantes; se houver vinheta, tela colorida ou transição, avance o `--start` para depois dela.

Abra a prévia e verifique de verdade: o rosto está inteiro? O conteúdo está legível e sem a webcam duplicada? Sobrou borda de interface? Ajuste os recortes e repita. A prévia leva um segundo; um render errado desperdiça minutos e o usuário só descobre no fim.

### 4. Renderize

```bash
python "${SKILL_DIR}/scripts/react.py" render --source "<video>" \
  --cam-crop "..." --content-crop "..." --start 12 --end 45 \
  --watermark "KICK.COM/CANAL" --out "<pasta-do-usuario>/corte_react.mp4"
```

Dois arquivos:

```bash
python "${SKILL_DIR}/scripts/react.py" render --cam "<reacao.mp4>" --content "<video.mp4>" \
  --start 0 --end 30 --audio mix --out "<saida.mp4>"
```

Salve o resultado na pasta de saída do usuário (veja "Pastas do usuário"), nunca só na pasta temporária. O script se recusa a sobrescrever um arquivo existente sem `--overwrite`; não passe essa opção sobre um arquivo que você não criou nesta conversa.

### 5. Confirme o resultado

O `render` imprime resolução, duração e presença de áudio. Depois extraia quadros do arquivo final (`frame` sem `--grid`) nos segundos 0, 1 e no meio, e olhe antes de dizer que ficou pronto: os dois primeiros precisam mostrar o rosto (veja "Os 3 primeiros segundos"); se não mostrarem, refaça com o `--start` adiantado. Informe ao usuário o caminho, a duração e qualquer coisa que não tenha conseguido verificar — o sincronismo de áudio, por exemplo, você não ouve.

### 6. Sugira a descrição de cada corte

Todo corte entregue vem acompanhado de uma sugestão de legenda para a postagem, sem o usuário precisar pedir — ele vai publicar o vídeo e escrever isso na hora é o que mais atrasa. Para cada clipe:

- **Descrição**: uma ou duas frases curtas, no tom informal de quem posta cortes (português do Brasil, pode usar "kkkk" e um emoji). Comece pelo gancho do momento, sem entregar o desfecho, e termine com uma chamada para ação que combine com o clipe: uma pergunta para comentar, "marca aquele amigo que…", "segue para a parte 2". Varie o CTA entre os clipes do mesmo lote; cinco legendas terminando em "segue aí" parecem automáticas.
- **Hashtags**: de 4 a 6, misturando as específicas (o streamer ou canal, o tema do momento, a plataforma da live) com uma ou duas amplas (`#cortes`, `#fyp`). Hashtag específica que encaixa vale mais que uma lista longa de genéricas.

Baseie-se só no que você sabe do trecho (a análise do vídeo, a transcrição, o que o usuário contou). Não invente nomes, falas ou fatos; se não souber quem é o streamer, deixe a hashtag do canal de fora e diga isso ao usuário.

Mostre as sugestões na resposta, junto de cada arquivo, e salve-as também em `descricoes.txt` na mesma pasta dos clipes, para ele copiar na hora de postar. Formato do arquivo:

```
01_nome_do_clipe.mp4
Descrição com o CTA aqui.
#hashtag1 #hashtag2 #hashtag3 #hashtag4

02_outro_clipe.mp4
...
```

## Opções

| Opção | O que faz |
|---|---|
| `--source` | Um arquivo com webcam e conteúdo no mesmo quadro |
| `--cam`, `--content` | Dois arquivos separados |
| `--cam-crop`, `--content-crop` | Regiões `x,y,w,h` (pixels ou frações) |
| `--split F` | Fração da altura para a câmera; padrão 0.317 |
| `--fit cover\|contain` | Como o conteúdo ocupa a área de baixo |
| `--start`, `--end` | Trecho (SS, MM:SS ou HH:MM:SS) |
| `--cam-start` | Início no arquivo da câmera, se diferente de `--start` |
| `--audio auto\|source\|cam\|content\|mix\|none` | Áudio; `auto` usa o do arquivo único, ou mistura os dois |
| `--title TEXTO` | Título/CTA abaixo da câmera, cobrindo o vazio do modo `contain`; `--title-color`, `--title-bg` ajustam |
| `--subs ARQUIVO.ass` | Legenda gerada pelo `legenda.py`, gravada no vídeo |
| `--watermark TEXTO` | Texto na divisa; `--watermark-size`, `--watermark-color`, `--font` ajustam |
| `--crf N` | Qualidade (padrão 20; menor é melhor e mais pesado) |
| `--fps N` | Padrão 30 |

## O que perguntar e o que decidir sozinho

Pergunte só o que não dá para deduzir: o sincronismo no modo de dois arquivos. O trecho não se pergunta — se o usuário não disse, o passo 0 acha. Decida sozinho os recortes, a proporção e o `--fit`, olhando o quadro — é para isso que a prévia existe.

Vários vídeos de uma vez: trate um por um, porque a posição da webcam muda de live para live. Reaproveite os recortes apenas entre clipes da mesma transmissão, e ainda assim confira uma prévia de cada.

## Limites

- A busca de momentos depende de áudio agitado e, para dar nota e título, da skill `watch` com o Gemini configurado.
- A legenda depende do modelo do Whisper em `~/.cache/corte-react/`; sem ele, os cortes saem sem legenda.
- O conteúdo de terceiros (o vídeo assistido, a live de outro criador) tem dono. Se o usuário perguntar sobre publicar, diga que a permissão e as regras da plataforma são com ele; não trate o corte como automaticamente liberado.
