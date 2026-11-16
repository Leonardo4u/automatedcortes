#!/usr/bin/env python3
"""Monta um vídeo vertical no formato react: câmera em cima, conteúdo embaixo.

Subcomandos:
  frame    extrai um quadro (com grade opcional) para localizar a webcam e o conteúdo
  preview  renderiza um único quadro do resultado, para conferir antes do render completo
  render   gera o vídeo final

Só usa a biblioteca padrão do Python, mais ffmpeg e ffprobe no PATH.
"""
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

OUT_W, OUT_H = 1080, 1920
PREROLL = 8.0  # segundos lidos antes do início pedido, para o decodificador achar um quadro-chave
DEFAULT_CAM_H = 608  # 1080 x 608 = 16:9, o topo medido nos cortes de referência

FONT_CANDIDATES = [
    'C:/Windows/Fonts/impact.ttf',
    'C:/Windows/Fonts/arialbd.ttf',
    '/System/Library/Fonts/Supplemental/Impact.ttf',
    '/System/Library/Fonts/Supplemental/Arial Bold.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
]


def die(msg):
    print(f'[react] ERRO: {msg}', file=sys.stderr)
    sys.exit(2)


def need(tool):
    if not shutil.which(tool):
        die(f'{tool} não encontrado no PATH. Instale o ffmpeg (inclui o ffprobe).')


def probe(path):
    if not Path(path).is_file():
        die(f'arquivo não encontrado: {path}')
    out = subprocess.run(
        ['ffprobe', '-v', 'error', '-print_format', 'json', '-show_streams', '-show_format', str(path)],
        capture_output=True, encoding='utf-8', errors='replace')
    if out.returncode != 0:
        die(f'ffprobe não conseguiu ler {path}: {out.stderr.strip()[:300]}')
    data = json.loads(out.stdout)
    video = next((s for s in data.get('streams', []) if s.get('codec_type') == 'video'), None)
    if not video:
        die(f'{path} não tem faixa de vídeo.')
    return {
        'width': int(video['width']),
        'height': int(video['height']),
        'duration': float(data.get('format', {}).get('duration') or 0),
        'has_audio': any(s.get('codec_type') == 'audio' for s in data.get('streams', [])),
    }


def parse_time(text):
    """Aceita SS, MM:SS ou HH:MM:SS (com decimais)."""
    if text is None:
        return None
    try:
        total = 0.0
        for part in str(text).split(':'):
            total = total * 60 + float(part)
    except ValueError:
        die(f'tempo inválido: {text!r} (use SS, MM:SS ou HH:MM:SS)')
    if total < 0:
        die(f'tempo negativo: {text!r}')
    return total


def parse_crop(spec, width, height, label):
    """'x,y,w,h' em pixels, ou em frações de 0 a 1 quando todos os valores são <= 1."""
    if not spec:
        return None
    try:
        x, y, w, h = (float(v) for v in spec.split(','))
    except ValueError:
        die(f'--{label}-crop precisa de quatro números "x,y,w,h"; recebi {spec!r}')
    if max(x, y, w, h) <= 1:
        x, y, w, h = x * width, y * height, w * width, h * height
    x, y = int(round(x)), int(round(y))
    w, h = int(w) // 2 * 2, int(h) // 2 * 2  # dimensões pares para o encoder
    if w < 16 or h < 16 or x < 0 or y < 0 or x + w > width or y + h > height:
        die(f'--{label}-crop {spec!r} sai do quadro de {width}x{height}.')
    return x, y, w, h


def ff_path(path):
    """Escapa um caminho para uso dentro de um filtro do ffmpeg (o ':' do Windows quebra o parser)."""
    return str(path).replace('\\', '/').replace(':', '\\:').replace("'", "\\'")


def find_font(explicit):
    if explicit:
        if not Path(explicit).is_file():
            die(f'fonte não encontrada: {explicit}')
        return explicit
    for candidate in FONT_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    die('nenhuma fonte encontrada para a marca d\'água; passe --font CAMINHO.ttf')


def split_lines(words, n):
    """Divide as palavras em n linhas de comprimento parecido (menor linha mais longa possível)."""
    if n <= 1 or len(words) <= 1:
        return [' '.join(words)]
    best = None
    for cut in range(1, len(words)):
        rest = split_lines(words[cut:], n - 1)
        candidate = [' '.join(words[:cut])] + rest
        longest = max(len(line) for line in candidate)
        if best is None or longest < best[0]:
            best = (longest, candidate)
    return best[1]


def layout_title(text, band_h, char_ratio, usable_w=OUT_W - 100):
    """Escolhe o número de linhas e o tamanho de fonte que deixam o título o maior possível na faixa."""
    words = text.upper().split()
    best = None
    for n in range(1, min(3, len(words)) + 1):
        lines = split_lines(words, n)
        longest = max(len(line) for line in lines)
        size = min(band_h * 0.84 / (n * 1.18), usable_w / (longest * char_ratio), 124)
        if best is None or size > best[1]:
            best = (lines, size)
    return best[0], int(best[1])


def cta_chains(args, tmpdir, video_label, seam_y, preview_at):
    """Placa de CTA sobre a divisa: entra deslizando, fica alguns segundos e sai.

    Devolve (cadeias de filtro, rótulo do vídeo resultante). Em prévia, a placa aparece parada.
    """
    dur = args.cta_duration
    if preview_at is not None and preview_at >= dur:
        return [], video_label  # a prévia pedida cai depois que a placa já saiu
    box_w, box_h, border, shadow = 880, 250, 9, 16
    font = find_font(args.font)
    ratio = 0.54 if 'impact' in Path(font).name.lower() else 0.64
    lines, size = layout_title(args.cta, box_h - 2 * border - 36, ratio, box_w - 2 * border - 70)
    line_h = size * 1.16
    top = (box_h - line_h * len(lines)) / 2 + (line_h - size) / 2
    life = dur + 0.5
    banner = (f'color=c=black@0.0:s={box_w + shadow}x{box_h + shadow}:r={args.fps}:d={life:.2f},format=rgba'
              f',drawbox=x={shadow}:y={shadow}:w={box_w}:h={box_h}:color=black@0.6:t=fill:replace=1'
              f',drawbox=x=0:y=0:w={box_w}:h={box_h}:color=black:t=fill:replace=1'
              f',drawbox=x={border}:y={border}:w={box_w - 2 * border}:h={box_h - 2 * border}'
              f':color={args.cta_color}:t=fill:replace=1')
    for i, line in enumerate(lines):
        line_file = Path(tmpdir) / f'cta_{i}.txt'
        line_file.write_text(line, encoding='utf-8')
        banner += (f",drawtext=fontfile='{ff_path(font)}':textfile='{ff_path(line_file)}':fontsize={size}"
                   f":fontcolor={args.cta_text_color}:x=({box_w}-text_w)/2:y={int(top + i * line_h)}")
    # leve inclinação, como um adesivo colado por cima do vídeo
    banner += ",rotate=-0.03:c=black@0.0:ow='rotw(-0.03)':oh='roth(-0.03)'"
    if preview_at is None:
        banner += f',fade=t=out:st={dur - 0.2:.2f}:d=0.2:alpha=1'
        slide = 0.28
        # entra da esquerda desacelerando; sai para a direita acelerando
        x = (f"if(lt(t,{slide}),(W-w)/2-((W-w)/2+w)*pow(1-t/{slide},3),"
             f"if(gt(t,{dur - slide:.2f}),(W-w)/2+(W-(W-w)/2)*pow((t-{dur - slide:.2f})/{slide},3),(W-w)/2))")
        overlay = f"overlay=x='{x}':y={seam_y}-h/2:enable='lt(t,{dur})':eof_action=pass"
    else:
        overlay = f'overlay=x=(W-w)/2:y={seam_y}-h/2:eof_action=pass'
    return [banner + '[cta]', f'[{video_label}][cta]{overlay}[with_cta]'], 'with_cta'


def fill(label_in, label_out, crop, w, h, mode, anchor='center'):
    """Cadeia de filtros que leva um vídeo até exatamente w x h."""
    head = f'[{label_in}]'
    if crop:
        x, y, cw, ch = crop
        head += f'crop={cw}:{ch}:{x}:{y},'
    if mode == 'cover':
        return [f'{head}scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1[{label_out}]']
    # contain: o vídeo inteiro aparece, sobre uma cópia desfocada de si mesmo
    return [
        f'{head}split=2[{label_out}_a][{label_out}_b]',
        f'[{label_out}_a]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},gblur=sigma=28,eq=brightness=-0.08[{label_out}_bg]',
        f'[{label_out}_b]scale={w}:{h}:force_original_aspect_ratio=decrease[{label_out}_fg]',
        f'[{label_out}_bg][{label_out}_fg]overlay=(W-w)/2:{"H-h" if anchor == "bottom" else "(H-h)/2"},setsar=1[{label_out}]',
    ]


def build(args, tmpdir, preview_at=None):
    """Devolve (argumentos de entrada, filter_complex, mapeamentos de saída)."""
    single = bool(args.source)
    if single and (args.cam or args.content):
        die('use --source (um arquivo só) OU --cam e --content (dois arquivos), não os dois.')
    if not single and not (args.cam and args.content):
        die('informe --source, ou então --cam e --content.')

    cam_file = args.source or args.cam
    content_file = args.source or args.content
    cam_info, content_info = probe(cam_file), probe(content_file)

    if single and not (args.cam_crop and args.content_crop):
        die('com --source, informe --cam-crop e --content-crop (rode "frame --grid" para localizá-los).')

    cam_crop = parse_crop(args.cam_crop, cam_info['width'], cam_info['height'], 'cam')
    content_crop = parse_crop(args.content_crop, content_info['width'], content_info['height'], 'content')

    cam_h = DEFAULT_CAM_H if args.split is None else int(round(OUT_H * args.split / 2)) * 2
    if not 200 <= cam_h <= OUT_H - 200:
        die('--split precisa ficar entre 0.11 e 0.89.')
    content_h = OUT_H - cam_h

    start = parse_time(args.start) or 0.0
    end = parse_time(args.end)
    cam_start = parse_time(args.cam_start)
    if cam_start is None:
        cam_start = start
    if end is not None and end <= start:
        die('--end precisa ser maior que --start.')
    if start >= content_info['duration'] > 0:
        die(f'--start ({start:.1f}s) passa do fim do vídeo ({content_info["duration"]:.1f}s).')
    offset = preview_at or 0.0

    # VODs gravados de live têm quadros-chave espaçados e mal marcados: ao pular direto para o instante
    # pedido, o decodificador só entrega imagem no quadro-chave seguinte, e o vídeo começa até alguns
    # segundos depois do áudio. Por isso a leitura começa PREROLL segundos antes e o excesso é cortado
    # dentro do filtro, onde o corte é exato.
    def seek(t):
        pre = min(PREROLL, t)
        return ['-ss', f'{t - pre:.3f}'], pre

    inputs, pres = [], []
    if single:
        ss, pre = seek(start + offset)
        inputs += ss + ['-i', str(cam_file)]
        pres = [pre]
        chains = [f'[0:v]trim=start={pre:.3f},setpts=PTS-STARTPTS,split=2[cam_src][content_src]']
    else:
        ss0, pre0 = seek(cam_start + offset)
        ss1, pre1 = seek(start + offset)
        inputs += ss0 + ['-i', str(cam_file)] + ss1 + ['-i', str(content_file)]
        pres = [pre0, pre1]
        chains = [f'[0:v]trim=start={pre0:.3f},setpts=PTS-STARTPTS[cam_src]',
                  f'[1:v]trim=start={pre1:.3f},setpts=PTS-STARTPTS[content_src]']
    cam_label, content_label = 'cam_src', 'content_src'

    def audio_of(index):
        """Áudio do arquivo `index`, cortado no mesmo ponto exato do vídeo."""
        chains.append(f'[{index}:a:0]atrim=start={pres[index]:.3f},asetpts=PTS-STARTPTS[au{index}]')
        return f'[au{index}]'

    chains += fill(cam_label, 'top', cam_crop, OUT_W, cam_h, 'cover')
    # Com título, o vídeo desce até a base e todo o espaço que sobraria vira a faixa do título,
    # em vez de ficar metade em cima e metade embaixo.
    anchor = 'bottom' if args.title and args.fit == 'contain' else 'center'
    chains += fill(content_label, 'bottom', content_crop, OUT_W, content_h, args.fit, anchor)
    chains.append(f'[top][bottom]vstack=inputs=2:shortest=1,fps={args.fps},format=yuv420p[stack]')
    video_label = 'stack'

    gap = 0
    if args.fit == 'contain':
        cw, ch = (content_crop[2], content_crop[3]) if content_crop else (content_info['width'], content_info['height'])
        scaled_h = min(content_h, int(OUT_W * ch / cw) // 2 * 2)
        gap = content_h - scaled_h if anchor == 'bottom' else (content_h - scaled_h) // 2

    if args.title:
        # Com espaço vazio entre a câmera e o vídeo (modo contain), o título ocupa exatamente esse espaço.
        # Sem espaço, vira uma faixa sobre o topo do conteúdo.
        band_h = gap if gap >= 90 else 170
        font = find_font(args.font)
        ratio = 0.54 if 'impact' in Path(font).name.lower() else 0.64
        lines, size = layout_title(args.title, band_h, ratio)
        line_h = size * 1.18
        top = cam_h + (band_h - line_h * len(lines)) / 2 + (line_h - size) / 2
        chain = f'[{video_label}]drawbox=x=0:y={cam_h}:w={OUT_W}:h={band_h}:color={args.title_bg}:t=fill'
        for i, line in enumerate(lines):
            line_file = Path(tmpdir) / f'title_{i}.txt'
            line_file.write_text(line, encoding='utf-8')
            chain += (f",drawtext=fontfile='{ff_path(font)}':textfile='{ff_path(line_file)}'"
                      f":fontsize={size}:fontcolor={args.title_color}:borderw={max(3, size // 14)}:bordercolor=black"
                      f":x=(w-text_w)/2:y={int(top + i * line_h)}")
        chains.append(chain + '[titled]')
        video_label = 'titled'

    if args.subs:
        if not Path(args.subs).is_file():
            die(f'legenda não encontrada: {args.subs}')
        # Antes da placa de CTA, para a placa passar por cima da legenda e não o contrário.
        chains.append(f"[{video_label}]ass='{ff_path(Path(args.subs).resolve())}'[subbed]")
        video_label = 'subbed'

    if args.cta:
        extra, video_label = cta_chains(args, tmpdir, video_label, cam_h, preview_at)
        chains += extra

    if args.watermark:
        text_file = Path(tmpdir) / 'watermark.txt'
        text_file.write_text(args.watermark, encoding='utf-8')
        font = find_font(args.font)
        chains.append(
            f"[{video_label}]drawtext=fontfile='{ff_path(font)}':textfile='{ff_path(text_file)}'"
            f":fontsize={args.watermark_size}:fontcolor={args.watermark_color}"
            f":borderw=5:bordercolor=black:x=(w-text_w)/2:y={cam_h}-text_h/2[marked]")
        video_label = 'marked'

    maps = ['-map', f'[{video_label}]']
    if preview_at is None:
        audio = args.audio
        if audio == 'auto':
            audio = 'source' if single else 'mix'
        if single:
            audio = 'source' if audio != 'none' else 'none'
            if audio == 'source' and cam_info['has_audio']:
                maps += ['-map', audio_of(0)]
        elif audio == 'cam' and cam_info['has_audio']:
            maps += ['-map', audio_of(0)]
        elif audio == 'content' and content_info['has_audio']:
            maps += ['-map', audio_of(1)]
        elif audio == 'mix':
            if cam_info['has_audio'] and content_info['has_audio']:
                chains.append(f'{audio_of(0)}{audio_of(1)}amix=inputs=2:duration=shortest:normalize=0,'
                              'alimiter=limit=0.95[mixed]')
                maps += ['-map', '[mixed]']
            elif cam_info['has_audio']:
                maps += ['-map', audio_of(0)]
            elif content_info['has_audio']:
                maps += ['-map', audio_of(1)]

    duration = None if end is None else end - start
    return inputs, ';'.join(chains), maps, duration, {'cam_h': cam_h, 'content_h': content_h, 'gap': gap}


def run_ffmpeg(cmd):
    result = subprocess.run(cmd, capture_output=True, encoding='utf-8', errors='replace')
    if result.returncode != 0:
        tail = '\n'.join(result.stderr.strip().splitlines()[-12:])
        die(f'ffmpeg falhou:\n{tail}')


def cmd_frame(args):
    info = probe(args.input)
    at = parse_time(args.at) or 0.0
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    filters = []
    if args.grid:
        # linhas a cada 10% do quadro: cada célula vale 0.1 nas coordenadas de --cam-crop / --content-crop
        filters.append('drawgrid=w=iw/10:h=ih/10:t=2:c=yellow@0.9')
    filters.append(f'scale={args.width}:-2')
    run_ffmpeg(['ffmpeg', '-v', 'error', '-y', '-ss', f'{at:.3f}', '-i', str(args.input),
                '-frames:v', '1', '-vf', ','.join(filters), str(out)])
    print(f'[react] quadro em {at:.1f}s salvo em {out}')
    print(f'[react] vídeo de origem: {info["width"]}x{info["height"]}, {info["duration"]:.1f}s, '
          f'áudio: {"sim" if info["has_audio"] else "não"}')
    if args.grid:
        print('[react] grade: 10 colunas x 10 linhas; cada linha amarela marca 0.1 do quadro.')


def cmd_preview(args):
    at = parse_time(args.at) or 0.0
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmpdir:
        inputs, graph, maps, _, dims = build(args, tmpdir, preview_at=at)
        graph += f';[{maps[1][1:-1]}]scale=540:-2[small]'
        run_ffmpeg(['ffmpeg', '-v', 'error', '-y', *inputs, '-filter_complex', graph,
                    '-map', '[small]', '-frames:v', '1', str(out)])
    print(f'[react] prévia salva em {out} (câmera {dims["cam_h"]}px, conteúdo {dims["content_h"]}px de 1920)')
    if dims['gap'] >= 90 and not args.title:
        print(f'[react] há {dims["gap"]}px vazios entre a câmera e o vídeo; --title "TEXTO" cobre esse espaço.')


def cmd_render(args):
    out = Path(args.out)
    if out.exists() and not args.overwrite:
        die(f'{out} já existe; escolha outro --out ou passe --overwrite.')
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmpdir:
        inputs, graph, maps, duration, dims = build(args, tmpdir)
        cmd = ['ffmpeg', '-v', 'error', '-y', *inputs, '-filter_complex', graph, *maps]
        if duration is not None:
            cmd += ['-t', f'{duration:.3f}']
        cmd += ['-c:v', 'libx264', '-preset', 'medium', '-crf', str(args.crf), '-pix_fmt', 'yuv420p',
                '-c:a', 'aac', '-b:a', '160k', '-ar', '44100', '-movflags', '+faststart', '-shortest', str(out)]
        run_ffmpeg(cmd)
    info = probe(out)
    print(f'[react] vídeo salvo em {out}')
    print(f'[react] {info["width"]}x{info["height"]}, {info["duration"]:.1f}s, '
          f'áudio: {"sim" if info["has_audio"] else "não"}, '
          f'câmera {dims["cam_h"]}px + conteúdo {dims["content_h"]}px')


def add_layout_args(p):
    p.add_argument('--source', help='um arquivo só (clipe de live) com a webcam e o conteúdo no mesmo quadro')
    p.add_argument('--cam', help='arquivo da câmera/reação (modo de dois arquivos)')
    p.add_argument('--content', help='arquivo do conteúdo assistido (modo de dois arquivos)')
    p.add_argument('--cam-crop', help='região da câmera "x,y,w,h" (pixels, ou frações de 0 a 1)')
    p.add_argument('--content-crop', help='região do conteúdo "x,y,w,h" (pixels, ou frações de 0 a 1)')
    p.add_argument('--split', type=float, help='fração da altura para a câmera (padrão 0.317 = 16:9)')
    p.add_argument('--fit', choices=['cover', 'contain'], default='cover',
                   help='cover corta o conteúdo para preencher; contain mostra inteiro sobre fundo desfocado')
    p.add_argument('--start', help='início do trecho (SS, MM:SS ou HH:MM:SS)')
    p.add_argument('--end', help='fim do trecho')
    p.add_argument('--cam-start', help='início no arquivo da câmera, se for diferente de --start')
    p.add_argument('--title', help='título/CTA logo abaixo da câmera; no modo contain cobre o espaço vazio')
    p.add_argument('--title-color', default='0xFFE600')
    p.add_argument('--title-bg', default='black@0.82', help='cor da faixa atrás do título')
    p.add_argument('--subs', help='legenda .ass gerada pelo legenda.py, queimada no vídeo')
    p.add_argument('--cta', help='placa animada sobre a divisa, que aparece no começo e some')
    p.add_argument('--cta-duration', type=float, default=3.0, help='segundos em que a placa fica na tela')
    p.add_argument('--cta-color', default='0xFFE600', help='cor de fundo da placa')
    p.add_argument('--cta-text-color', default='black')
    p.add_argument('--watermark', help='texto na divisa entre câmera e conteúdo')
    p.add_argument('--watermark-size', type=int, default=46)
    p.add_argument('--watermark-color', default='white')
    p.add_argument('--font', help='arquivo .ttf para a marca d\'água')
    p.add_argument('--fps', type=int, default=30)


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8')
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)

    p = sub.add_parser('frame', help='extrai um quadro para localizar webcam e conteúdo')
    p.add_argument('input')
    p.add_argument('--at', default='0')
    p.add_argument('--out', required=True)
    p.add_argument('--grid', action='store_true', help='desenha grade de 10x10')
    p.add_argument('--width', type=int, default=1280)
    p.set_defaults(func=cmd_frame)

    p = sub.add_parser('preview', help='renderiza um quadro do resultado')
    add_layout_args(p)
    p.add_argument('--at', default='0', help='segundos depois de --start')
    p.add_argument('--out', required=True)
    p.set_defaults(func=cmd_preview, audio='none')

    p = sub.add_parser('render', help='gera o vídeo final')
    add_layout_args(p)
    p.add_argument('--audio', choices=['auto', 'source', 'cam', 'content', 'mix', 'none'], default='auto')
    p.add_argument('--crf', type=int, default=20, help='qualidade do vídeo (menor = melhor; 18 a 23)')
    p.add_argument('--out', required=True)
    p.add_argument('--overwrite', action='store_true')
    p.set_defaults(func=cmd_render)

    args = parser.parse_args()
    need('ffmpeg')
    need('ffprobe')
    args.func(args)


if __name__ == '__main__':
    main()
