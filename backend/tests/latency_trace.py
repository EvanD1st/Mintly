"""Opt-in credential-free HTTP timing for disposable feature audits."""
import json
import os
from pathlib import Path
import time
import re
from functools import lru_cache
from collections import Counter, defaultdict
from contextvars import ContextVar

import httpx

_case = ContextVar('latency_case', default='setup')
_rows = []
_results = []
_original = None


@lru_cache(maxsize=3)
def route_patterns(surface):
    from app.main import app
    from app.services.automatic_signer import app as signer
    from app.custody_import import app as importer
    target = {'api': app, 'signer': signer, 'importer': importer}[surface]
    # OpenAPI also resolves the lazy included routers in recent FastAPI versions.
    paths = target.openapi()['paths']
    return [(method.upper(), path, re.compile('^'+re.sub(r'\{[^}]+\}', '[^/]+', path)+'$'))
            for path, methods in paths.items() for method in methods
            if method.lower() in ('get','post','put','patch','delete','head','options')]


def template(request):
    surface = {'signer':'signer','import':'importer','importer':'importer'}.get(request.url.host,'api')
    for method, path, pattern in route_patterns(surface):
        if request.method == method and pattern.fullmatch(request.url.path):
            return surface, path
    return surface, '/unmatched'  # Never retain IDs, query strings or URLs.


def pytest_configure(config):
    global _original
    _original = httpx.AsyncClient.send
    async def measured(client, request, *args, **kwargs):
        if request.url.host not in ('test', 'signer', 'importer', 'import'):
            return await _original(client, request, *args, **kwargs)
        surface, route = template(request)
        started = time.perf_counter()
        code = 0
        try:
            response = await _original(client, request, *args, **kwargs)
            code = response.status_code
            return response
        finally:
            finished = time.perf_counter()
            _rows.append(dict(test=_case.get(), surface=surface, method=request.method,
                route=route, status=code, ms=round((finished-started)*1000, 3),
                start=started, end=finished))
    httpx.AsyncClient.send = measured


def pytest_runtest_setup(item):
    _case.set(item.nodeid)


def pytest_runtest_logreport(report):
    if report.when == 'call' or report.failed:
        _results.append(dict(test=report.nodeid, phase=report.when, outcome=report.outcome,
            known_failure=getattr(report,'wasxfail',None)))


def percentile(values, fraction):
    values = sorted(values)
    return values[min(len(values)-1, int((len(values)-1)*fraction))]


def pytest_sessionfinish(session, exitstatus):
    httpx.AsyncClient.send = _original
    grouped = defaultdict(list)
    for row in _rows:
        grouped[(row['surface'], row['method'], row['route'])].append(row)
    summaries = []
    for (surface, method, route), rows in grouped.items():
        values = [r['ms'] for r in rows]
        summaries.append(dict(surface=surface, method=method, route=route, requests=len(rows),
            p50_ms=percentile(values,.5), p95_ms=percentile(values,.95), p99_ms=percentile(values,.99),
            max_ms=max(values), statuses=dict(Counter(str(r['status']) for r in rows))))
    edges = sorted([(r['start'],1) for r in _rows]+[(r['end'],-1) for r in _rows])
    active = peak = 0
    for _, delta in edges:
        active += delta; peak = max(peak, active)
    report = dict(environment=os.environ.get('MINTLY_LATENCY_LABEL','disposable'),
        exit_status=int(exitstatus), tests=_results, routes=sorted(summaries,key=lambda r:r['p95_ms'],reverse=True),
        http_requests=len(_rows), peak_overlapping_requests=peak,
        route_inventory=[dict(surface=surface,method=method,route=path)
            for surface in ('api','signer','importer') for method,path,_ in route_patterns(surface)],
        samples=[{k:v for k,v in row.items() if k not in ('start','end')} for row in _rows],
        limitations=['In-process ASGI timings exclude WAN and device rendering.',
            'Expected negative/fault cases are included; HTTP error counts alone are not a glitch rate.',
            'Disposable custody fixtures use cheap KDF parameters, not production signing costs.',
            'Provider data is controlled; local EVM receipt times are not mainnet inclusion times.'])
    target = Path(os.environ.get('MINTLY_LATENCY_REPORT','latency-report.json'))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
