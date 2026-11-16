#!/usr/bin/env python3
"""Acha sozinho os melhores momentos de um vídeo longo (live, VOD) para virar cortes.

Como funciona:
  1. mede o volume do áudio segundo a segundo e escolhe os picos de agitação
     (riso, grito, comemoração), afastados entre si;
  2. extrai um trecho curto e leve em volta de cada pico e junta todos numa compilação;
  3. se a skill "watch" estiver instalada com o Gemini configurado, pede UMA análise da
     compilação inteira: o que acontece em cada trecho, uma nota e o melhor início/fim.
     Um pedido só por vídeo, porque a chave gratuita do Gemini tem limite diário baixo;
  4. grava um resumo em momentos.json e uma folha de quadros com grade para cada
     candidato aprovado, para localizar a webcam e o conteúdo.

Só usa a biblioteca padrão do Python, mais ffmpeg/ffprobe.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from statistics import median

LOTE = 15  # trechos por pedido ao Gemini
SEG_BEFORE, SEG_LEN = 50, 80  # cada trecho começa 50s antes do pico e dura 80s

FONT_CANDIDATES = [
    'C:/Windows/Fonts/arialbd.ttf',
    '/System/Library/Fonts/Supplemental/Arial Bold.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
]

QUESTION = (
    'Este vídeo é uma compilação de {n} trechos independentes de uma mesma live/vídeo longo, colados em '
    'sequência. Cada trecho tem o rótulo "TRECHO N" no alto da imagem e ocupa este intervalo da compilação: '
    '{tabela}. Pode haver uma câmera pequena de um streamer reagindo em um canto. Avalie CADA trecho '
    'separadamente como candidato a corte de TikTok. Responda em português. Para cada trecho escreva de 2 a 4 '
    'linhas dizendo o que acontece e o que é dito (com timestamps da compilação) e, logo depois, UMA linha '
    'exatamente neste formato, sem negrito e sem markdown:\n'
    'RESUMO N: nota=<0 a 10>; inicio=<segundos>; fim=<segundos>; canto=<canto da câmera pequena ou nenhum>; '
    'titulo=<título curto de até 6 palavras>; descricao=<uma frase com o que acontece>\n'
    'Regras: "inicio" e "fim" são segundos contados desde o começo da COMPILAÇÃO, ficam dentro do intervalo '
    'daquele trecho e delimitam um corte de 15 a 50 segundos que começa numa frase completa e termina depois '
    'da reação. A nota mede se existe um momento engraçado, surpreendente ou marcante que funcione sozinho; '
    'seja rigoroso, conversa comum sem clímax vale 4 ou menos. Não pule nenhum trecho.'
)
SUMMARY_RE = re.compile(
    r'RESUMO\s*(\d+)\s*:\s*nota\s*=\s*([\d.,]+)[^;\n]*;\s*inicio\s*=\s*([\d.,:]+)[^;\n]*;'
    r'\s*fim\s*=\s*([\d.,:]+)[^;\n]*;\s*canto\s*=\s*([^;\n]*);\s*titulo\s*=\s*([^;\n]*)'
    r'(?:;\s*descricao\s*=\s*([^\n]*))?', re.IGNORECASE)


def log(msg):
    print(f'[momentos] {msg}', file=sys.stderr, flush=True)


def die(msg):
    print(f'[momentos] ERRO: {msg}', file=sys.stderr)
    sys.exit(2)


def run(cmd, **kwargs):
    return subprocess.run(cmd, capture_output=True, encoding='utf-8', errors='replace', **kwargs)


def duration_of(video):
    out = run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(video)])
    try:
        return float(out.stdout.strip())
    except ValueError:
        die(f'não consegui ler a duração de {video}: {out.stderr.strip()[:200]}')


def loudness_per_second(video):
    """Volume RMS (dB) de cada segundo, calculado pelo próprio ffmpeg."""
    # A reamostragem precisa estar DENTRO do filtro: como opção de saída (-ar) ela roda depois,
    # e os blocos de 4000 amostras deixariam de valer um segundo cada.
    out = run(['ffmpeg', '-v', 'error', '-i', str(video), '-map', '0:a:0', '-vn',
               '-af', 'aformat=channel_layouts=mono,aresample=4000,asetnsamples=n=4000:p=0,'
                      'astats=metadata=1:reset=1,'
                      'ametadata=mode=print:key=lavfi.astats.Overall.RMS_level:file=-',
               '-f', 'null', '-'])
    values = []
    for line in out.stdout.splitlines():
        if 'RMS_level=' in line:
            raw = line.split('=', 1)[1].strip()
            try:
                values.append(max(float(raw), -90.0))
            except ValueError:
                values.append(-90.0)
    if len(values) < 30:
        die('o vídeo não tem áudio utilizável (ou é curto demais) para achar momentos pelo volume.')
    return values


def pick_peaks(db, top, min_gap, spread=True):
    """Segundos em que o áudio mais passa do nível normal da vizinhança."""
    n = len(db)
    step, half = 10, 150
    base = []
    for i in range(0, n, step):
        base += [median(db[max(0, i - half):i + half])] * step
    excess = [max(db[i] - base[i], 0.0) for i in range(n)]
    win = 20
    prefix = [0.0]
    for value in excess:
        prefix.append(prefix[-1] + value)
    score = []
    for i in range(n):
        a, b = max(0, i - win // 2), min(n, i + win // 2)
        score.append((prefix[b] - prefix[a]) / win)
    order = sorted(range(n), key=lambda k: score[k], reverse=True)
    picked = []
    if spread:
        # Primeiro uma cota igual para cada hora do vídeo. Sem isso, a parte mais barulhenta da live
        # (uma gameplay em grupo, por exemplo) leva todos os candidatos e o resto nem é analisado.
        hours = max(1, -(-n // 3600))
        quota = max(1, top // hours)
        per_hour = {}
        for i in order:
            hour = i // 3600
            if per_hour.get(hour, 0) < quota and all(abs(i - p) >= min_gap for p in picked):
                picked.append(i)
                per_hour[hour] = per_hour.get(hour, 0) + 1
            if len(picked) >= top:
                break
    for i in order:  # as vagas que sobrarem vão para os picos mais fortes do vídeo todo
        if len(picked) >= top:
            break
        if all(abs(i - p) >= min_gap for p in picked):
            picked.append(i)
    return [(p, round(score[p], 1)) for p in sorted(picked)]


def fmt(seconds):
    seconds = int(seconds)
    return f'{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}'


def mmss(seconds):
    seconds = int(round(seconds))
    return f'{seconds // 60:02d}:{seconds % 60:02d}'


def ff_path(path):
    return str(path).replace('\\', '/').replace(':', '\\:').replace("'", "\\'")


def extract_segment(video, start, number, out):
    """Trecho leve, sempre no mesmo formato (para colar sem recodificar), com o rótulo TRECHO N."""
    filters = ('scale=640:360:force_original_aspect_ratio=decrease,pad=640:360:(ow-iw)/2:(oh-ih)/2,'
               'setsar=1,fps=15')
    font = next((f for f in FONT_CANDIDATES if Path(f).is_file()), None)
    if font:
        filters += (f",drawtext=fontfile='{ff_path(font)}':text='TRECHO {number}':fontsize=26:fontcolor=white"
                    ':box=1:boxcolor=black@0.7:boxborderw=8:x=(w-text_w)/2:y=10')
    run(['ffmpeg', '-v', 'error', '-y', '-ss', f'{start:.2f}', '-i', str(video), '-t', str(SEG_LEN),
         '-vf', filters, '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '30', '-pix_fmt', 'yuv420p',
         '-c:a', 'aac', '-b:a', '56k', '-ac', '1', '-ar', '22050', str(out)])
    return out.is_file() and out.stat().st_size > 0


def build_compilation(segments, out_dir, name='compilacao.mp4'):
    listing = out_dir / (Path(name).stem + '.txt')
    listing.write_text(''.join(f"file '{str(s).replace(chr(92), '/')}'\n" for s in segments), encoding='utf-8')
    out = out_dir / name
    result = run(['ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', str(listing),
                  '-c', 'copy', str(out)])
    if not out.is_file() or out.stat().st_size == 0:
        die(f'não consegui montar a compilação: {result.stderr.strip()[-300:]}')
    return out


def find_watch():
    script = Path.home() / '.claude' / 'skills' / 'watch' / 'scripts' / 'watch.py'
    return script if script.is_file() else None


def ask_gemini(watch, compilation, question, report, key):
    """Um pedido ao Gemini pela skill watch. Devolve (resposta ou None, motivo da falha)."""
    marker = f'<!-- {key} -->'
    if report.is_file():  # resposta boa de uma rodada anterior, para os mesmos trechos: reaproveita
        previous = report.read_text(encoding='utf-8')
        if previous.startswith(marker) and 'RESUMO' in previous:
            log('reaproveitando a análise da rodada anterior (nenhum pedido novo ao Gemini).')
            return previous, None
    env = dict(os.environ, WATCH_GEMINI_TIMEOUT='1500')  # a compilação é longa; o padrão de 600s é curto
    reason = 'falha'
    for attempt in range(3):
        if attempt:
            log('Gemini sobrecarregado; esperando para tentar de novo...')
            time.sleep(45 * attempt)
        out = run([sys.executable, str(watch), str(compilation), '--engine', 'gemini', '--question', question],
                  env=env)
        if 'Answer (from Gemini)' in out.stdout:
            answer = out.stdout.split('Answer (from Gemini)', 1)[1].strip()
            report.write_text(f'{marker}\n{answer}\n', encoding='utf-8')
            return answer, None
        detail = out.stdout[-900:] + out.stderr[-300:]
        (report.parent / 'analise_erro.txt').write_text(detail, encoding='utf-8')
        if 'Gemini quota' in out.stdout or 'HTTP 429' in out.stdout:
            # Cota esgotada: insistir só gasta mais pedidos.
            wait = re.search(r'retry in ([0-9hms.]+)', out.stdout)
            return None, 'cota' + (f' (volta em {wait.group(1)})' if wait else '')
        if 'Gemini service' not in out.stdout and 'HTTP 503' not in out.stdout:
            return None, 'erro'  # chave ausente, vídeo recusado etc.: tentar de novo não resolve
        reason = 'sobrecarga'
    return None, reason


def find_model(explicit):
    """Modelo do Whisper (formato ggml, do whisper.cpp) para a transcrição local."""
    if explicit:
        return Path(explicit) if Path(explicit).is_file() else None
    folder = Path.home() / '.cache' / 'corte-react'
    for name in ('ggml-large-v3-turbo.bin', 'ggml-large-v3.bin', 'ggml-medium.bin', 'ggml-small.bin', 'ggml-base.bin'):
        if (folder / name).is_file():
            return folder / name
    return None


def has_whisper_filter():
    return 'whisper.cpp' in run(['ffmpeg', '-hide_banner', '-h', 'filter=whisper']).stdout


def transcribe(segment, model, language, out):
    """Transcreve um trecho com o Whisper embutido no ffmpeg. Devolve linhas '[mm:ss] fala'."""
    if not (out.is_file() and out.stat().st_size > 0):
        out.unlink(missing_ok=True)
        # queue alto: o Whisper recebe blocos longos de áudio e acerta mais do que em pedaços de 3s
        chain = (f"aformat=sample_rates=16000:channel_layouts=mono,whisper=model='{ff_path(model)}'"
                 f":language={language}:queue=25:destination='{ff_path(out)}':format=srt")
        result = run(['ffmpeg', '-v', 'error', '-y', '-i', str(segment), '-vn', '-af', chain, '-f', 'null', '-'])
        if not out.is_file():
            return None, result.stderr.strip()[-300:]
    lines, stamp = [], None
    for raw in out.read_text(encoding='utf-8', errors='replace').splitlines():
        raw = raw.strip()
        match = re.match(r'(\d+):(\d+):(\d+)[,.]\d+\s*-->', raw)
        if match:
            stamp = int(match.group(1)) * 3600 + int(match.group(2)) * 60 + int(match.group(3))
        elif raw and not raw.isdigit() and stamp is not None:
            lines.append(f'[{mmss(stamp)}] {raw}')
            stamp = None
    return lines, None


def to_seconds(text):
    text = text.strip().replace(',', '.').rstrip('.')
    if ':' in text:
        total = 0.0
        for part in text.split(':'):
            total = total * 60 + float(part)
        return total
    return float(text)


def parse_answer(answer, offsets):
    """Lê as linhas RESUMO N. offsets[N-1] = (início, fim) do trecho N dentro da compilação."""
    found = {}
    for m in SUMMARY_RE.finditer(answer.replace('*', '').replace('`', '')):
        number = int(m.group(1))
        if number not in offsets or number in found:
            continue
        try:
            nota, start, end = to_seconds(m.group(2)), to_seconds(m.group(3)), to_seconds(m.group(4))
        except ValueError:
            continue
        seg_a, seg_b = offsets[number]
        if not (seg_a - 2 <= start < end <= seg_b + 2):
            # fora do intervalo do trecho: o modelo pode ter contado a partir do início do trecho
            if 0 <= start < end <= (seg_b - seg_a) + 2:
                start, end = start + seg_a, end + seg_a
            else:
                continue
        found[number] = {'nota': nota, 'rel_inicio': max(0.0, start - seg_a), 'rel_fim': min(seg_b, end) - seg_a,
                         'canto': m.group(5).strip(), 'titulo': m.group(6).strip(),
                         'descricao': (m.group(7) or '').strip()}
    return found


def grid_sheet(video, start, end, out):
    """Três quadros (início, meio, fim) lado a lado, cada um com grade de 10x10."""
    times = [start + 1, (start + end) / 2, max(start + 1, end - 1)]
    cmd = ['ffmpeg', '-v', 'error', '-y']
    for t in times:
        cmd += ['-ss', f'{t:.2f}', '-i', str(video)]
    graph = ''.join(f'[{i}:v]drawgrid=w=iw/10:h=ih/10:t=3:c=yellow@0.85,scale=640:-2[g{i}];' for i in range(3))
    cmd += ['-filter_complex', graph + '[g0][g1][g2]hstack=inputs=3', '-frames:v', '1', str(out)]
    run(cmd)


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8')
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('video')
    parser.add_argument('--out-dir', required=True, help='pasta de trabalho (temporária) para trechos e análises')
    parser.add_argument('--top', type=int, default=14, help='quantos picos de áudio analisar')
    parser.add_argument('--so-os-mais-altos', action='store_true',
                        help='não reparte os candidatos por hora; pega só os picos mais fortes do vídeo todo')
    parser.add_argument('--min-gap', type=int, default=150, help='distância mínima entre picos, em segundos')
    parser.add_argument('--min-nota', type=float, default=7.0, help='nota mínima para um momento ser aprovado')
    parser.add_argument('--no-gemini', action='store_true',
                        help='não envia nada ao Google; escolhe só pelo volume do áudio')
    parser.add_argument('--resposta', help='(teste) arquivo com uma resposta pronta, em vez de chamar o Gemini')
    parser.add_argument('--local', action='store_true',
                        help='pula o Gemini e transcreve os trechos nesta máquina (nada sai do computador)')
    parser.add_argument('--modelo', help='arquivo ggml do Whisper; padrão: o melhor em ~/.cache/corte-react')
    parser.add_argument('--idioma', default='pt', help='idioma falado no vídeo, para a transcrição local')
    parser.add_argument('--grades', help='só gera folhas de quadros: "N:inicio:fim,N:inicio:fim" em segundos do vídeo')
    args = parser.parse_args()

    for tool in ('ffmpeg', 'ffprobe'):
        if not shutil.which(tool):
            die(f'{tool} não encontrado no PATH.')
    video = Path(args.video)
    if not video.is_file():
        die(f'arquivo não encontrado: {video}')
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    total = duration_of(video)

    if args.grades:
        # Depois de escolher os cortes pela transcrição: folhas de quadros só dos escolhidos.
        for item in args.grades.split(','):
            try:
                number, start, end = item.split(':')
                start, end = float(start), float(end)
            except ValueError:
                die(f'--grades espera "N:inicio:fim" em segundos; recebi {item!r}')
            sheet = out_dir / f'grade_{int(number):02d}.jpg'
            grid_sheet(video, start, end, sheet)
            print(f'trecho {number}: {sheet}')
        return

    # A medição é a parte lenta e não muda entre rodadas: fica guardada na pasta de trabalho.
    cache = out_dir / 'volume.json'
    stamp = [video.stat().st_size, int(video.stat().st_mtime)]
    db = None
    if cache.is_file():
        saved = json.loads(cache.read_text(encoding='utf-8'))
        if saved.get('stamp') == stamp:
            db = saved['db']
            log('reaproveitando a medição de volume da rodada anterior.')
    if db is None:
        log(f'medindo o volume de {fmt(total)} de áudio (leva de segundos a poucos minutos)...')
        db = loudness_per_second(video)
        cache.write_text(json.dumps({'stamp': stamp, 'db': db}), encoding='utf-8')
    if abs(len(db) - total) > max(30, total * 0.05):
        die(f'a medição de áudio devolveu {len(db)} segundos para um vídeo de {total:.0f}s; '
            'os tempos não seriam confiáveis.')
    peaks = pick_peaks(db, args.top, args.min_gap, spread=not args.so_os_mais_altos)
    log(f'{len(peaks)} picos de agitação encontrados.')

    watch = None if args.no_gemini else find_watch()
    mode = 'gemini' if (watch or args.resposta) and not args.no_gemini else 'audio'
    if not args.no_gemini and mode == 'audio':
        log('skill "watch" não encontrada: seguindo só com o volume do áudio.')

    candidates = []
    for number, (peak, score) in enumerate(peaks, 1):
        seg_start = max(0.0, peak - SEG_BEFORE)
        candidates.append({'trecho': number, 'pico': peak, 'pico_hms': fmt(peak), 'agitacao': score,
                           'trecho_inicio': seg_start,
                           # sem análise, o corte padrão cobre a subida e a reação em volta do pico
                           'corte_inicio': max(0.0, peak - 20), 'corte_fim': min(total, peak + 12),
                           'nota': None, 'canto': None, 'titulo': None, 'descricao': None})

    failure = None
    if mode == 'gemini':
        log('extraindo um trecho leve de cada pico...')
        segments, lengths = [], []
        for c in candidates:
            seg = out_dir / f'trecho_{c["trecho"]:02d}_{c["pico"]:05d}.mp4'
            if not (seg.is_file() and seg.stat().st_size > 0):
                if not extract_segment(video, c['trecho_inicio'], c['trecho'], seg):
                    die(f'não consegui extrair o trecho do pico {c["pico_hms"]}.')
            segments.append(seg)
            lengths.append(duration_of(seg))
        # Uma compilação por lote de até LOTE trechos (uns 20 minutos): um pedido ao Gemini por lote.
        batches = [list(range(i, min(i + LOTE, len(segments)))) for i in range(0, len(segments), LOTE)]
        parsed, answer = {}, None
        if args.local:
            failure = 'pedido do usuário (--local)'
        elif not watch and not args.resposta:
            failure = 'skill watch ausente'
        else:
            answers = []
            for b, batch in enumerate(batches, 1):
                offsets, cursor = {}, 0.0
                for i in batch:
                    offsets[i + 1] = (cursor, cursor + lengths[i])
                    cursor += lengths[i]
                compilation = build_compilation([segments[i] for i in batch], out_dir, f'compilacao_{b}.mp4')
                tabela = '; '.join(f'TRECHO {n} de {mmss(a)} a {mmss(z)} ({a:.0f}s a {z:.0f}s)'
                                   for n, (a, z) in offsets.items())
                question = QUESTION.format(n=len(offsets), tabela=tabela)
                if args.resposta:
                    reply = Path(args.resposta).read_text(encoding='utf-8')
                else:
                    log(f'enviando a compilação {b} de {len(batches)} ({mmss(cursor)}) ao Gemini '
                        '(pode levar vários minutos)...')
                    key = 'picos ' + ','.join(str(candidates[i]['pico']) for i in batch)
                    reply, failure = ask_gemini(watch, compilation, question, out_dir / f'analise_{b}.md', key)
                if not reply:
                    break  # se um lote falha, a reserva local cuida de todos, com o mesmo critério
                answers.append(reply)
                parsed.update(parse_answer(reply, offsets))
            else:
                answer = '\n\n'.join(answers)
                (out_dir / 'analise.md').write_text(answer + '\n', encoding='utf-8')
        if answer:
            for c in candidates:
                item = parsed.get(c['trecho'])
                if not item:
                    continue
                c.update(nota=item['nota'], canto=item['canto'], titulo=item['titulo'],
                         descricao=item['descricao'])
                # um segundo de folga de cada lado, para não cortar a primeira e a última sílaba
                c['corte_inicio'] = max(0.0, c['trecho_inicio'] + item['rel_inicio'] - 1)
                c['corte_fim'] = min(total, c['trecho_inicio'] + item['rel_fim'] + 1)
        else:
            # Reserva: sem o Gemini, transcreve os trechos aqui mesmo. Quem dá a nota é quem ler o texto.
            model = find_model(args.modelo)
            if not model:
                log('sem modelo do Whisper em ~/.cache/corte-react: não há reserva local.')
            elif not has_whisper_filter():
                log('este ffmpeg não tem o filtro "whisper": não há reserva local.')
            else:
                mode = 'transcricao'
                log(f'Gemini indisponível ({failure}). Transcrevendo {len(segments)} trechos com {model.name} '
                    '(pode levar de alguns a vários minutos)...')
                parts = [f'# Transcrição dos trechos candidatos\n\nMotivo: Gemini indisponível ({failure}). '
                         'Os tempos entre colchetes contam do início de cada trecho; some ao "início do trecho" '
                         'para ter o tempo no vídeo original.\n']
                for c, seg in zip(candidates, segments):
                    lines, error = transcribe(seg, model, args.idioma,
                                              out_dir / f'transcricao_{c["pico"]:05d}.srt')
                    c['transcricao'] = len(lines) if lines is not None else None
                    parts.append(f'\n## TRECHO {c["trecho"]} — início do trecho em {c["trecho_inicio"]:.0f}s '
                                 f'({fmt(c["trecho_inicio"])}), pico de áudio aos {mmss(c["pico"] - c["trecho_inicio"])}\n')
                    parts.append('\n'.join(lines) if lines else f'(sem fala reconhecida{": " + error if error else ""})')
                    log(f'  trecho {c["trecho"]}: {len(lines) if lines else 0} falas')
                (out_dir / 'transcricoes.md').write_text('\n'.join(parts) + '\n', encoding='utf-8')

    for c in candidates:
        c['aprovado'] = c['nota'] >= args.min_nota if c['nota'] is not None else mode == 'audio'
        c['corte_inicio_hms'], c['corte_fim_hms'] = fmt(c['corte_inicio']), fmt(c['corte_fim'])
        if c['aprovado']:
            sheet = out_dir / f'grade_{c["trecho"]:02d}.jpg'
            grid_sheet(video, c['corte_inicio'], c['corte_fim'], sheet)
            c['grade'] = str(sheet)

    candidates.sort(key=lambda c: (-(c['nota'] if c['nota'] is not None else -1), -c['agitacao']))
    missing = [c['trecho'] for c in candidates if mode == 'gemini' and c['nota'] is None]
    result = {'video': str(video), 'duracao': total, 'modo': mode, 'min_nota': args.min_nota,
              'falha': failure, 'sem_nota': missing, 'candidatos': candidates}
    summary_file = out_dir / 'momentos.json'
    summary_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')

    print(f'modo: {mode} | resumo: {summary_file}')
    if mode == 'transcricao':
        print(f'RESERVA LOCAL: o Gemini não respondeu ({failure}), então os trechos foram transcritos nesta '
              f'máquina. Leia {out_dir / "transcricoes.md"}, dê você mesmo a nota e o início/fim de cada trecho, '
              'e gere as folhas de quadros dos escolhidos com --grades "N:inicio:fim,...". '
              'Os tempos abaixo são só o padrão em volta do pico.')
    elif failure and failure.startswith('cota'):
        print(f'ATENÇÃO: a cota da chave do Gemini acabou {failure[4:].strip()}. O plano gratuito tem limite '
              'diário de pedidos. Rode o mesmo comando depois que a cota voltar (o áudio e os trechos já estão '
              'prontos), ou use --no-gemini para escolher só pelo áudio.')
    elif failure:
        print(f'ATENÇÃO: a análise do Gemini não veio ({failure}; detalhe em analise_erro.txt). Rode o mesmo '
              'comando de novo mais tarde, ou use --no-gemini.')
    elif missing:
        print(f'ATENÇÃO: o Gemini respondeu, mas sem nota legível para os trechos {missing}. '
              'Leia analise.md para esses.')
    print('trecho | nota | início | fim | canto | título')
    for c in candidates:
        nota = '-' if c['nota'] is None else f'{c["nota"]:g}'
        mark = 'OK' if c['aprovado'] else '  '
        print(f'{mark} {c["trecho"]:>2} | {nota:>4} | {c["corte_inicio_hms"]} ({c["corte_inicio"]:.0f}s) | '
              f'{c["corte_fim_hms"]} ({c["corte_fim"]:.0f}s) | {c["canto"] or "?"} | {c["titulo"] or "?"}')
        if c['descricao']:
            print(f'      {c["descricao"]}')


if __name__ == '__main__':
    main()
