#!/usr/bin/env python3
"""Formato clássico para quem fala em tela cheia: o quadro 16:9 no meio, fundo desfocado,
título fixo numa placa amarela em cima e a legenda (legenda.py) logo abaixo do vídeo.

Serve para trechos sem "vídeo embaixo" (vlog, podcast, streamer só conversando) em que a pessoa
se mexe demais para um recorte vertical fixo do rosto: o quadro inteiro fica visível, então ninguém
sai de cena.

Subcomandos:
  preview  renderiza um quadro do resultado
  render   gera o vídeo final

A legenda deve ser gerada com --split 0.75 no legenda.py, para ficar logo abaixo do vídeo.
Só usa a biblioteca padrão do Python, mais ffmpeg e ffprobe no PATH.
"""
import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from react import (OUT_W, OUT_H, die, need, probe, parse_time, ff_path,  # noqa: E402
                   split_lines, run_ffmpeg)

VIDEO_Y = 600          # topo do vídeo no quadro de saída
TITLE_Y = 410          # centro da placa de título
CAPTION_SPLIT = 0.75   # --split a passar ao legenda.py (legenda centrada a 1440px)
TITLE_STYLE = ('Style: Titulo,Arial Black,{size},&H00111111,&H00111111,&H0000E6FF,&H0000E6FF,'
               '-1,0,0,0,100,100,0,0,3,22,0,5,40,40,0,1')
CAPTION_STYLE = ('Style: Fala,Arial Black,84,&H00FFFFFF,&H00FFFFFF,&H00000000,&HA0000000,'
                 '-1,0,0,0,100,100,0,0,1,8,4,5,40,40,0,1')
ASS_HEADER = ('[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nWrapStyle: 2\n'
              'ScaledBorderAndShadow: yes\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, '
              'SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, '
              'ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, '
              'Encoding\n' + CAPTION_STYLE + '\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, '
              'MarginR, MarginV, Effect, Text\n')


def ass_time(seconds):
    h, rest = divmod(max(seconds, 0), 3600)
    m, s = divmod(rest, 60)
    return f'{int(h)}:{int(m):02d}:{s:05.2f}'


def title_layout(text):
    """Uma ou duas linhas, a fonte maior que caiba em ~940px de largura."""
    words = []
    for word in text.upper().split():
        # número ou numeral romano curto fica grudado na palavra anterior ("GTA 6", "GTA V")
        if words and (word.isdigit() or word in ('V', 'VI', 'IV', 'III', 'II')):
            words[-1] += ' ' + word
        else:
            words.append(word)
    best = None
    for n in (1, 2):
        if n > len(words):
            break
        lines = split_lines(words, n)
        longest = max(len(line) for line in lines)
        size = min(84, 940 / (longest * 0.68))
        if best is None or size > best[1] + 6:  # prefere uma linha, a menos que duas fiquem bem maiores
            best = (lines, size)
    return [line.replace(' ', ' ') for line in best[0]], int(best[1])


def build_ass(subs, title, duration, tmpdir):
    if subs:
        if not Path(subs).is_file():
            die(f'legenda não encontrada: {subs}')
        text = Path(subs).read_text(encoding='utf-8-sig')
    else:
        text = ASS_HEADER
    lines = text.splitlines()
    out = []
    for line in lines:
        out.append(line)
        if title and line.startswith('Style: Fala'):
            out.append(TITLE_STYLE.format(size=title['size']))
        if title and line.startswith('Format: Layer'):
            out.append(f'Dialogue: 1,0:00:00.00,{ass_time(duration)},Titulo,,0,0,0,,'
                       f'{{\\an5\\pos(540,{TITLE_Y})\\frz2\\fad(250,0)}}' + '\\N'.join(title['lines']))
    if title and not any(l.startswith('Style: Fala') for l in lines):
        die('a legenda passada não tem o estilo "Fala" do legenda.py; gere-a com o legenda.py.')
    path = Path(tmpdir) / 'classico.ass'
    path.write_text('\n'.join(out) + '\n', encoding='utf-8')
    return path


def build(args, tmpdir):
    info = probe(args.source)
    start = parse_time(args.start) or 0.0
    end = parse_time(args.end) if args.end else info['duration']
    if end <= start:
        die('--end precisa ser maior que --start.')
    if start >= info['duration']:
        die(f'--start ({start:.1f}s) passa do fim do vídeo ({info["duration"]:.1f}s).')
    duration = min(end, info['duration']) - start
    if not 1.0 <= args.zoom <= 2.0:
        die('--zoom vai de 1.0 (quadro inteiro) a 2.0.')
    if not -1.0 <= args.shift <= 1.0:
        die('--shift vai de -1 (encosta à esquerda) a 1 (encosta à direita).')

    # escala o quadro para OUT_W*zoom de largura e corta OUT_W, deslocado por --shift
    big_w = int(round(OUT_W * args.zoom / 2)) * 2
    big_h = int(round(big_w * info['height'] / info['width'] / 2)) * 2
    slack = big_w - OUT_W
    crop_x = int(round(slack / 2 * (1 + args.shift)))
    title = None
    if args.title:
        lines, size = title_layout(args.title)
        title = {'lines': lines, 'size': size}
    ass = build_ass(args.subs, title, duration, tmpdir) if (args.subs or title) else None

    graph = (f'[0:v]fps={args.fps},split=2[a][b];'
             f'[a]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,crop={OUT_W}:{OUT_H},'
             f'boxblur=24:2,eq=brightness=-0.18[bg];'
             f'[b]scale={big_w}:{big_h},crop={OUT_W}:{big_h}:{crop_x}:0[fg];'
             f'[bg][fg]overlay=0:{VIDEO_Y}')
    graph += f",ass='{ff_path(ass)}'" if ass else ''
    graph += ',format=yuv420p[v]'
    inputs = ['-ss', f'{start:.3f}', '-t', f'{duration:.3f}', '-i', str(args.source)]
    return inputs, graph, duration, info, {'video_h': big_h, 'title': title}


def cmd_preview(args):
    at = parse_time(args.at) or 0.0
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmpdir:
        inputs, graph, duration, _, dims = build(args, tmpdir)
        if at >= duration:
            die(f'--at ({at:.1f}s) passa da duração do trecho ({duration:.1f}s).')
        graph += f';[v]trim=start={at:.3f},setpts=PTS-STARTPTS,scale=540:-2[p]'
        run_ffmpeg(['ffmpeg', '-v', 'error', '-y', *inputs, '-filter_complex', graph,
                    '-map', '[p]', '-frames:v', '1', str(out)])
    print(f'[classico] prévia salva em {out} (vídeo de {dims["video_h"]}px a partir de y={VIDEO_Y})')
    if dims['title']:
        print(f'[classico] título: {" / ".join(dims["title"]["lines"])} (fonte {dims["title"]["size"]})')


def cmd_render(args):
    out = Path(args.out)
    if out.exists() and not args.overwrite:
        die(f'{out} já existe; escolha outro --out ou passe --overwrite.')
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmpdir:
        inputs, graph, duration, info, _ = build(args, tmpdir)
        cmd = ['ffmpeg', '-v', 'error', '-y', *inputs, '-filter_complex', graph, '-map', '[v]']
        if info['has_audio']:
            cmd += ['-map', '0:a:0', '-c:a', 'aac', '-b:a', '160k', '-ar', '44100']
        cmd += ['-c:v', 'libx264', '-preset', 'medium', '-crf', str(args.crf), '-pix_fmt', 'yuv420p',
                '-movflags', '+faststart', str(out)]
        run_ffmpeg(cmd)
    result = probe(out)
    print(f'[classico] vídeo salvo em {out}')
    print(f'[classico] {result["width"]}x{result["height"]}, {result["duration"]:.1f}s, '
          f'áudio: {"sim" if result["has_audio"] else "não"}')


def add_args(p):
    p.add_argument('--source', required=True, help='vídeo de origem')
    p.add_argument('--start', help='início do trecho (SS, MM:SS ou HH:MM:SS)')
    p.add_argument('--end', help='fim do trecho')
    p.add_argument('--title', help='texto da placa amarela fixa em cima (quebra em até 2 linhas sozinho)')
    p.add_argument('--subs', help='legenda .ass do legenda.py, gerada com --split 0.75 --depois-de 0')
    p.add_argument('--zoom', type=float, default=1.185,
                   help='amplia o quadro antes de cortar as laterais (1.0 = inteiro; padrão 1.185)')
    p.add_argument('--shift', type=float, default=0.0,
                   help='desloca o corte das laterais: -1 esquerda, 0 centro, 1 direita')
    p.add_argument('--fps', type=int, default=30)


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8')
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)

    p = sub.add_parser('preview', help='renderiza um quadro do resultado')
    add_args(p)
    p.add_argument('--at', default='0', help='segundos depois de --start')
    p.add_argument('--out', required=True)
    p.set_defaults(func=cmd_preview)

    p = sub.add_parser('render', help='gera o vídeo final')
    add_args(p)
    p.add_argument('--crf', type=int, default=20)
    p.add_argument('--out', required=True)
    p.add_argument('--overwrite', action='store_true')
    p.set_defaults(func=cmd_render)

    args = parser.parse_args()
    need('ffmpeg')
    need('ffprobe')
    args.func(args)


if __name__ == '__main__':
    main()
