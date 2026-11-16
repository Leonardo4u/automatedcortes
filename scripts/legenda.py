#!/usr/bin/env python3
"""Gera a legenda de um corte no estilo "palavra que acende": poucas palavras por vez sobre a divisa,
e a palavra que está sendo falada muda de cor e dá um pulinho.

Dois passos, para dar chance de revisar o texto antes de ele ir gravado no vídeo:
  1. legenda.py VIDEO --start S --end E --out corte.ass
       transcreve o trecho com o Whisper embutido no ffmpeg, palavra por palavra, e grava
       corte.palavras.tsv (início, fim e palavra; revisável) e corte.ass (pronto para queimar);
  2. se alguma palavra saiu errada, corrija-a em corte.palavras.tsv e rode
       legenda.py --from-palavras corte.palavras.tsv --out corte.ass
       para refazer o .ass sem transcrever de novo.

Só usa a biblioteca padrão do Python, mais ffmpeg.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

OUT_W, OUT_H = 1080, 1920


def die(msg):
    print(f'[legenda] ERRO: {msg}', file=sys.stderr)
    sys.exit(2)


def run(cmd):
    return subprocess.run(cmd, capture_output=True, encoding='utf-8', errors='replace')


def ff_path(path):
    return str(path).replace('\\', '/').replace(':', '\\:').replace("'", "\\'")


def find_model(explicit):
    if explicit:
        return Path(explicit) if Path(explicit).is_file() else None
    folder = Path.home() / '.cache' / 'corte-react'
    for name in ('ggml-large-v3-turbo.bin', 'ggml-large-v3.bin', 'ggml-medium.bin', 'ggml-small.bin', 'ggml-base.bin'):
        if (folder / name).is_file():
            return folder / name
    return None


def parse_time(text):
    total = 0.0
    for part in str(text).split(':'):
        total = total * 60 + float(part)
    return total


def transcribe_words(video, start, end, model, language, raw_srt):
    """Áudio do trecho -> lista [início, fim, palavra]. max_len=1 faz o Whisper soltar uma palavra por vez."""
    raw_srt.unlink(missing_ok=True)
    queue = int(end - start) + 5  # a fala inteira de uma vez, para não cortar palavra no meio
    chain = (f"aformat=sample_rates=16000:channel_layouts=mono,whisper=model='{ff_path(model)}'"
             f":language={language}:queue={queue}:max_len=1"
             f":destination='{ff_path(raw_srt)}':format=srt")
    result = run(['ffmpeg', '-v', 'error', '-y', '-ss', f'{start:.3f}', '-t', f'{end - start:.3f}',
                  '-i', str(video), '-vn', '-af', chain, '-f', 'null', '-'])
    if not raw_srt.is_file():
        die(f'a transcrição falhou: {result.stderr.strip()[-300:]}')
    words, t0, t1 = [], None, None
    stamp = re.compile(r'(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)')
    for raw in raw_srt.read_text(encoding='utf-8', errors='replace').splitlines():
        raw = raw.strip()
        match = stamp.match(raw)
        if match:
            g = [int(x) for x in match.groups()]
            t0 = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
            t1 = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
        elif raw and t0 is not None:  # a linha logo após o tempo é o texto, mesmo quando é só um número ("30")
            if not re.fullmatch(r'[\[\(\*].*[\]\)\*]', raw):  # [música], *risos* não viram legenda
                words.append([t0, t1, raw])
            t0 = None
    return words


def smooth(words, total):
    """Os tempos por palavra do Whisper são aproximados: no começo de uma frase ele costuma marcar várias
    palavras no mesmo instante. Aqui cada trecho contínuo de fala tem os tempos redistribuídos, metade
    pelo que o Whisper disse e metade pelo tamanho das palavras, para o destaque andar junto da voz."""
    runs, current = [], []
    for word in words:
        if current and word[0] - current[-1][1] > 0.30:
            runs.append(current)
            current = []
        current.append(word)
    if current:
        runs.append(current)
    result, prev_end = [], 0.0
    for r, group in enumerate(runs):
        t0, t1 = group[0][0], group[-1][1]
        zeros = 0
        for word in group:
            if word[1] - word[0] < 0.06:
                zeros += 1
            else:
                break
        # palavras "empilhadas" no início foram faladas antes: o trecho recua para o silêncio anterior
        t0 = max(prev_end + 0.02, t0 - 0.22 * zeros)
        next_start = runs[r + 1][0][0] if r + 1 < len(runs) else total
        t1 = max(t1, t0 + 0.16 * len(group))
        t1 = min(t1, max(next_start - 0.02, t0 + 0.1))
        span = max(t1 - t0, 0.05)
        weights = [max(len(re.sub(r'\W', '', w[2])), 1) + 1.5 for w in group]
        cursor, wsum = t0, sum(weights)
        for i, word in enumerate(group):
            by_len = cursor + span * weights[i] / wsum
            by_whisper = min(max(word[1], cursor + 0.08), t1)
            end = (by_len + by_whisper) / 2 if i + 1 < len(group) else t1
            end = max(end, cursor + 0.10)
            result.append([round(cursor, 3), round(min(end, t1) if i + 1 < len(group) else t1, 3), word[2]])
            cursor = result[-1][1]
        prev_end = t1
    return result


def phrases(words, max_words, max_chars):
    """Agrupa as palavras no que aparece junto na tela: quebra em pontuação, em pausa e no limite."""
    groups, current = [], []
    for word in words:
        if current:
            chars = sum(len(w[2]) for w in current) + len(current) + len(word[2])
            pause = word[0] - current[-1][1] > 0.25
            ended = current[-1][2][-1:] in '.?!'
            if len(current) >= max_words or chars > max_chars or pause or ended:
                groups.append(current)
                current = []
        current.append(word)
    if current:
        groups.append(current)
    return groups


def shown(word):
    text = word.upper().rstrip('.,;:')  # ponto e vírgula somem; ? e ! ficam, porque mudam o tom
    return text.replace('{', '(').replace('}', ')').replace('\\', '/')


def write_ass(groups, path, center_y, font, size, color, after, pop=22):
    def stamp(t):
        cs = int(round(t * 100))
        return f'{cs // 360000}:{cs % 360000 // 6000:02d}:{cs % 6000 // 100:02d}.{cs % 100:02d}'
    head = (
        '[Script Info]\nScriptType: v4.00+\n'
        f'PlayResX: {OUT_W}\nPlayResY: {OUT_H}\nWrapStyle: 2\nScaledBorderAndShadow: yes\n\n'
        '[V4+ Styles]\n'
        'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, '
        'Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, '
        'MarginL, MarginR, MarginV, Encoding\n'
        f'Style: Fala,{font},{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&HA0000000,-1,0,0,0,100,100,0,0,1,8,4,5,'
        '40,40,0,1\n\n'
        '[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'
    )
    events = []
    for g, group in enumerate(groups):
        # segura a última palavra um instante, para não sumir no susto, mas nunca por cima do bloco
        # seguinte: dois blocos na tela ao mesmo tempo ficam um atrás do outro, na mesma posição
        group_end = group[-1][1] + 0.12
        if g + 1 < len(groups):
            group_end = max(group[-1][1], min(group_end, groups[g + 1][0][0]))
        for i, (start, end, _) in enumerate(group):
            stop = group[i + 1][0] if i + 1 < len(group) else group_end
            if stop <= after:
                continue  # enquanto a placa de CTA está na tela, a legenda espera
            start = max(start, after)
            parts = []
            for j, (_, _, text) in enumerate(group):
                if j == i:
                    # a palavra falada agora: muda de cor e cresce direto até o tamanho final, sem passar dele.
                    # (O usuário testou com quique, saltando a 135% antes de assentar, e não gostou;
                    # testou 114% e achou pouco. Ficou em 122%, crescimento simples.)
                    low, rest = 100, 100 + pop
                    parts.append(f'{{\\c{color}\\fscx{low}\\fscy{low}\\t(0,90,\\fscx{rest}\\fscy{rest})}}'
                                 f'{shown(text)}{{\\c&HFFFFFF&\\fscx100\\fscy100}}')
                else:
                    parts.append(shown(text))
            entrance = '\\fad(70,0)' if i == 0 or start == after else ''
            line = f'{{\\an5\\pos({OUT_W // 2},{center_y}){entrance}}}' + ' '.join(parts)
            events.append(f'Dialogue: 0,{stamp(start)},{stamp(stop)},Fala,,0,0,0,,{line}')
    path.write_text(head + '\n'.join(events) + '\n', encoding='utf-8-sig')
    return len(events)


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8')
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('video', nargs='?', help='vídeo de origem (o mesmo passado ao react.py)')
    p.add_argument('--start', help='início do corte no vídeo de origem')
    p.add_argument('--end', help='fim do corte')
    p.add_argument('--from-palavras', help='refaz o .ass a partir de um .palavras.tsv revisado, sem transcrever')
    p.add_argument('--out', required=True, help='arquivo .ass de saída (o .palavras.tsv fica ao lado)')
    p.add_argument('--split', type=float, default=0.5, help='o mesmo --split do corte: a legenda fica na divisa')
    p.add_argument('--depois-de', type=float, default=3.0,
                   help='a legenda só aparece depois deste instante (a duração da placa de CTA; 0 = desde o início)')
    p.add_argument('--fonte', default='Arial Black')
    p.add_argument('--tamanho', type=int, default=84)
    p.add_argument('--cor', default='FFE600', help='cor da palavra falada, em hexadecimal RRGGBB')
    p.add_argument('--crescimento', type=int, default=22,
                   help='quanto a palavra falada fica maior que as outras, em %% (0 desliga)')
    p.add_argument('--palavras', type=int, default=3, help='máximo de palavras na tela de cada vez')
    p.add_argument('--caracteres', type=int, default=17, help='máximo de caracteres na tela de cada vez')
    p.add_argument('--idioma', default='pt')
    p.add_argument('--modelo', help='arquivo ggml do Whisper; padrão: o melhor em ~/.cache/corte-react')
    args = p.parse_args()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    seam = int(round(OUT_H * args.split / 2)) * 2
    rgb = args.cor.lstrip('#')
    if not re.fullmatch(r'[0-9A-Fa-f]{6}', rgb):
        die('--cor precisa ser RRGGBB, por exemplo FFE600.')
    color = f'&H{rgb[4:6]}{rgb[2:4]}{rgb[0:2]}&'.upper()  # o formato .ass escreve as cores como BGR

    if args.from_palavras:
        words = []
        for line in Path(args.from_palavras).read_text(encoding='utf-8-sig').splitlines():
            cols = line.split('\t')
            if len(cols) >= 3 and cols[2].strip():
                words.append([float(cols[0]), float(cols[1]), cols[2].strip()])
        if not words:
            die(f'nenhuma palavra em {args.from_palavras}')
        table = Path(args.from_palavras)
    else:
        if not (args.video and args.start and args.end):
            die('informe o vídeo, --start e --end (ou --from-palavras).')
        start, end = parse_time(args.start), parse_time(args.end)
        model = find_model(args.modelo)
        if not model:
            die('modelo do Whisper não encontrado em ~/.cache/corte-react.')
        raw = out.with_suffix('.cru.srt')
        words = smooth(transcribe_words(args.video, start, end, model, args.idioma, raw), end - start)
        if not words:
            die('nenhuma fala reconhecida no trecho.')
        table = out.with_suffix('.palavras.tsv')
        table.write_text(''.join(f'{a:.3f}\t{b:.3f}\t{w}\n' for a, b, w in words), encoding='utf-8')

    groups = phrases(words, args.palavras, args.caracteres)
    count = write_ass(groups, out, seam, args.fonte, args.tamanho, color, args.depois_de, args.crescimento)
    print(f'[legenda] {len(words)} palavras em {len(groups)} blocos | revisável: {table}')
    print(f'[legenda] pronta para queimar: {out} ({count} eventos, centrada na divisa a {seam}px, '
          f'a partir de {args.depois_de:g}s)')
    for group in groups:
        print(f'  {group[0][0]:6.2f} -> {group[-1][1]:6.2f}  ' + ' '.join(w[2] for w in group))


if __name__ == '__main__':
    main()
