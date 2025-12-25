#!/usr/bin/env python3
"""
clean_and_tag_m3u.py

Reads liste.m3u and writes cleaned_liste.m3u where every entry has standardized
EXTINF metadata (tvg-id, tvg-name, tvg-logo, group-title). Uses section headers
in the playlist to infer group-title when available. Fills missing logos using
reasonable defaults per group.

Usage:
    python3 scripts/clean_and_tag_m3u.py liste.m3u

Optional: --check to perform HEAD requests to verify URLs (requests required).
"""
import re
import argparse
from urllib.parse import urlparse

def sanitize_id(name):
    # create a safe id from name
    s = name.strip()
    s = re.sub(r"\s+", '.', s)
    s = re.sub(r"[^A-Za-z0-9._-]", '', s)
    return s or 'unknown'

# default logos per group
DEFAULT_LOGOS = {
    'SİNEMALAR': 'https://i.hizliresim.com/i21k4te.png',
    'FİLMLER': 'https://i.hizliresim.com/i21k4te.png',
    'FİLM': 'https://i.hizliresim.com/i21k4te.png',
    'BELGESEL': 'https://upload.wikimedia.org/wikipedia/commons/1/1b/Documentary_icon.png',
    'YEDEK': 'https://i.hizliresim.com/i21k4te.png',
    '7/24': 'https://i.hizliresim.com/i21k4te.png',
    'DEFAULT': 'https://i.hizliresim.com/i21k4te.png'
}

# patterns that indicate a section header (these EXTINF lines contain the section name)
SECTION_KEYWORDS = [
    ('SİNEMALAR', re.compile(r'(?i)sinema|filmler|sinemalar')), 
    ('BELGESEL', re.compile(r'(?i)belgesel|belgeseller|documentary')),
    ('YEDEK', re.compile(r'(?i)yede?k|yedekler')), 
    ('7/24', re.compile(r'(?i)7/24|7/24 yayın|7/24 yayin')),
    ('FİLMLER', re.compile(r'(?i)filmler|filmler 🎬|filmler'))
]

ATTR_RE = re.compile(r'(\w+?)="(.*?)"')
EXTINF_RE = re.compile(r'^(?P<prefix>#EXTINF[^,]*,)(?P<title>.*)$', re.I)

def parse_extinf_attrs(line):
    # extract attributes from EXTINF line
    attrs = dict(ATTR_RE.findall(line))
    # extract title after the last comma
    m = EXTINF_RE.match(line)
    title = m.group('title').strip() if m else ''
    return attrs, title

def build_extinf(attrs, title):
    # ensure order: tvg-id, tvg-name, tvg-logo, group-title
    parts = []
    for k in ('tvg-id','tvg-name','tvg-logo','group-title'):
        v = attrs.get(k)
        if v:
            parts.append(f'{k}="{v}"')
    joined = ' '.join(parts)
    return f'#EXTINF:-1 {joined},{title}'


def detect_section_from_extinf(line):
    # check if this EXTINF line looks like a section header
    _, title = parse_extinf_attrs(line)
    t = title.upper()
    for key, rx in SECTION_KEYWORDS:
        if rx.search(title):
            return key
    return None


def normalize_lines(lines):
    out = []
    prev_blank = False
    for l in lines:
        s = l.rstrip('\n').rstrip('\r')
        if s.strip() == '':
            if not prev_blank:
                out.append('')
            prev_blank = True
        else:
            out.append(s.strip())
            prev_blank = False
    # trim trailing blank
    while out and out[-1] == '':
        out.pop()
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument('file', help='input m3u file (liste.m3u)')
    p.add_argument('--check', action='store_true', help='perform HEAD checks for URLs (requires requests)')
    args = p.parse_args()

    with open(args.file, encoding='utf-8', errors='replace') as f:
        raw = f.readlines()
    lines = normalize_lines(raw)

    out_lines = []
    current_group = None
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.upper().startswith('#EXTM3U'):
            out_lines.append('#EXTM3U')
            i += 1
            continue
        if line.upper().startswith('#EXTINF'):
            attrs, title = parse_extinf_attrs(line)
            # detect if this is a section header
            sec = detect_section_from_extinf(line)
            if sec:
                # treat as section marker
                current_group = sec
                # keep the section header but ensure group/title/logo if missing
                attrs.setdefault('tvg-name', title)
                # use group title same as key
                attrs.setdefault('group-title', sec)
                # set default logo for section
                attrs.setdefault('tvg-logo', DEFAULT_LOGOS.get(sec, DEFAULT_LOGOS['DEFAULT']))
                # tvg-id derived from title
                attrs.setdefault('tvg-id', sanitize_id(title))
                out_lines.append(build_extinf(attrs, title))
                # next line (media) copy as-is if exists
                j = i+1
                if j < len(lines) and not lines[j].upper().startswith('#EXTINF'):
                    out_lines.append(lines[j])
                    i = j+1
                else:
                    i += 1
                continue
            # not a pure section header, treat as entry
            # find the URL line (next non-empty non-EXTINF)
            url = None
            j = i+1
            while j < len(lines) and lines[j].startswith('#'):
                j += 1
            if j < len(lines):
                url = lines[j]
            # infer group-title: prefer existing attribute, else current_group, else DEFAULT
            group = attrs.get('group-title') or current_group or 'DEFAULT'
            attrs.setdefault('group-title', group)
            # tvg-name: use existing or title
            name = attrs.get('tvg-name') or title or (url or '')
            attrs.setdefault('tvg-name', name)
            # tvg-id: derive if missing
            attrs.setdefault('tvg-id', sanitize_id(attrs.get('tvg-name','')))
            # tvg-logo: choose based on group
            logo = attrs.get('tvg-logo')
            if not logo:
                k = group.upper()
                # try exact match in DEFAULT_LOGOS else DEFAULT
                attrs['tvg-logo'] = DEFAULT_LOGOS.get(k, DEFAULT_LOGOS['DEFAULT'])
            # rebuild extinf line
            out_lines.append(build_extinf(attrs, attrs.get('tvg-name')))
            # append url line if present
            if url:
                out_lines.append(url)
                i = j+1
            else:
                i = j
            continue
        else:
            # non-EXTINF lines (could be stray or headers), copy
            out_lines.append(line)
            i += 1

    out_path = 'cleaned_' + args.file
    with open(out_path, 'w', encoding='utf-8') as f:
        for ln in out_lines:
            f.write(ln + '\n')
    print('Wrote', out_path)

    if args.check:
        try:
            import requests
            print('Checking URLs (this may take a while)')
            entries = []
            k = 0
            while k < len(out_lines):
                if out_lines[k].upper().startswith('#EXTINF'):
                    url = None
                    if k+1 < len(out_lines) and not out_lines[k+1].startswith('#'):
                        url = out_lines[k+1]
                    entries.append((out_lines[k], url))
                    k += 2
                else:
                    k += 1
            ok = 0
            bad = []
            for ext, url in entries:
                if not url:
                    bad.append((ext, '<missing>'))
                    continue
                try:
                    r = requests.head(url, timeout=6, allow_redirects=True)
                    status = r.status_code
                    if status >= 400:
                        r = requests.get(url, timeout=6, stream=True, allow_redirects=True)
                        status = r.status_code
                    if status < 400:
                        ok += 1
                    else:
                        bad.append((ext, f'HTTP {status}'))
                except Exception as e:
                    bad.append((ext, str(e)))
            print(f'OK: {ok}/{len(entries)}')
            if bad:
                print('Bad entries:')
                for e,reason in bad:
                    print('-', e, '->', reason)
        except Exception:
            print('requests not available; --check requires requests')

if __name__ == '__main__':
    main()
