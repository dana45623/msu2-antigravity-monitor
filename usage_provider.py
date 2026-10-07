import json
import os
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path


class UsageProvider:
    def get(self):
        raise NotImplementedError


class LocalJsonProvider(UsageProvider):
    def __init__(self, path='usage.json'):
        self.path = Path(path)

    def get(self):
        return json.loads(self.path.read_text(encoding='utf-8'))


class ChatGPTUsageProvider(UsageProvider):
    """Read the signed-in ChatGPT/Codex allowance from the local Codex app-server.

    Codex exposes account/rateLimits/read over its local JSONL app-server protocol.
    The 300-minute primary window is the 5-hour meter and the 10080-minute
    secondary window is the weekly meter. The backend reports usedPercent, so the
    display value is 100 - usedPercent (percent left).
    """

    def __init__(self, codex_path=None, timeout=12):
        self.codex_path = Path(codex_path) if codex_path else self._find_codex()
        self.timeout = timeout

    @staticmethod
    def _find_codex():
        root = Path(os.environ.get('LOCALAPPDATA', '')) / 'OpenAI' / 'Codex' / 'bin'
        matches = sorted(root.glob('*/codex.exe'), key=lambda p: p.stat().st_mtime, reverse=True)
        if not matches:
            raise RuntimeError('找不到本機 Codex app-server；請先安裝並登入 Codex。')
        return matches[0]

    def get(self):
        popen_kwargs = {}
        if os.name == 'nt':
            popen_kwargs['creationflags'] = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            popen_kwargs['startupinfo'] = startupinfo

        proc = subprocess.Popen(
            [str(self.codex_path), 'app-server', '--stdio'],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='replace',
            bufsize=1,
            **popen_kwargs,
        )
        messages = []
        done = threading.Event()

        def reader():
            try:
                for line in proc.stdout:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    messages.append(msg)
                    if msg.get('id') == 2:
                        done.set()
                        return
            finally:
                done.set()

        thread = threading.Thread(target=reader, daemon=True)
        thread.start()
        try:
            self._send(proc, {
                'id': 1,
                'method': 'initialize',
                'params': {
                    'clientInfo': {'name': 'msu2-gpt-usage-display', 'version': '1.0.0'},
                    'capabilities': {},
                },
            })
            self._wait_for_id(messages, 1, done, self.timeout)
            self._send(proc, {
                'id': 2,
                'method': 'account/rateLimits/read',
                'params': {'excludeResetCreditDetails': True, 'supportsLunaReserve': False},
            })
            response = self._wait_for_id(messages, 2, done, self.timeout)
            if 'error' in response:
                raise RuntimeError(f"Codex rate-limit read failed: {response['error']}")
            result = response.get('result') or {}
            snapshot = result.get('rateLimits') or {}
            return self._convert(snapshot)
        finally:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except Exception:
                proc.kill()

    @staticmethod
    def _send(proc, obj):
        proc.stdin.write(json.dumps(obj, separators=(',', ':')) + '\n')
        proc.stdin.flush()

    @staticmethod
    def _wait_for_id(messages, request_id, done, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for msg in messages:
                if msg.get('id') == request_id:
                    return msg
            if done.wait(0.05):
                for msg in messages:
                    if msg.get('id') == request_id:
                        return msg
                break
        raise RuntimeError(f'Codex app-server timeout waiting for request {request_id}.')

    @staticmethod
    def _convert(snapshot):
        windows = [snapshot.get('primary'), snapshot.get('secondary')]
        windows = [w for w in windows if isinstance(w, dict)]
        five = next((w for w in windows if w.get('windowDurationMins') == 300), None)
        week = next((w for w in windows if w.get('windowDurationMins') == 10080), None)
        if not five or not week:
            raise RuntimeError(f'Codex did not return expected 5-hour/weekly windows: {snapshot!r}')

        reset_ts = week.get('resetsAt')
        reset = datetime.fromtimestamp(reset_ts).strftime('%m/%d %H:%M') if reset_ts else '--'
        return normalize({
            'five_hour': 100 - int(five['usedPercent']),
            'week': 100 - int(week['usedPercent']),
            'reset': reset,
        })


def normalize(data):
    return {
        'five_hour': max(0, min(100, int(data['five_hour']))),
        'week': max(0, min(100, int(data['week']))),
        'reset': str(data['reset'])[:16],
    }


class AntigravityUsageProvider(UsageProvider):
    """Read real-time Claude/GPT model quota from local Antigravity language_server.exe.

    Antigravity's local language_server.exe exposes Connect-RPC endpoint:
    /exa.language_server_pb.LanguageServerService/GetUserStatus
    authenticated via the per-session --csrf_token argument on 127.0.0.1.
    """

    def __init__(self, timeout=3.0):
        import ssl
        self.timeout = timeout
        self._cached_endpoint = None  # (scheme, port, csrf_token)
        self._ssl_ctx = ssl._create_unverified_context()

    @staticmethod
    def _popen_hidden_kwargs():
        kwargs = {}
        if os.name == 'nt':
            kwargs['creationflags'] = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = subprocess.SW_HIDE
            kwargs['startupinfo'] = si
        return kwargs

    def _discover_candidates(self):
        import re
        kw = self._popen_hidden_kwargs()
        ps_cmd = (
            "Get-CimInstance Win32_Process | "
            "Where-Object Name -eq 'language_server.exe' | "
            "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"
        )
        res = subprocess.run(
            ['powershell.exe', '-NoProfile', '-Command', ps_cmd],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=8,
            **kw,
        )
        raw = (res.stdout or '').strip()
        if not raw:
            raise RuntimeError('找不到執行中的 Antigravity (language_server.exe)；請確認 Antigravity 已開啟。')

        parsed = json.loads(raw)
        procs = parsed if isinstance(parsed, list) else [parsed]

        # Map PID -> listening local ports via netstat
        ns = subprocess.run(
            ['netstat.exe', '-ano', '-p', 'tcp'],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=5,
            **kw,
        )
        pid_ports = {}
        for line in (ns.stdout or '').splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[3].upper() == 'LISTENING' and parts[1].startswith('127.0.0.1:'):
                try:
                    port = int(parts[1].rsplit(':', 1)[1])
                    pid = int(parts[4])
                    pid_ports.setdefault(pid, []).append(port)
                except ValueError:
                    continue

        candidates = []
        for p in procs:
            pid = int(p.get('ProcessId') or 0)
            cmd = str(p.get('CommandLine') or '')
            m = re.search(r'--?csrf_token(?:=|\s+)([^\s"]+)', cmd)
            if not m:
                continue
            csrf = m.group(1)
            for port in sorted(set(pid_ports.get(pid, []))):
                candidates.append(('https', port, csrf))
                candidates.append(('http', port, csrf))
        if not candidates:
            raise RuntimeError('找不到 Antigravity language_server 本地連接埠或 CSRF token。')
        return candidates

    def _post_rpc(self, scheme, port, csrf, method_name):
        import ssl
        import urllib.request

        url = f'{scheme}://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/{method_name}'
        payload = json.dumps({
            'metadata': {
                'ideName': 'antigravity',
                'extensionName': 'antigravity',
                'locale': 'en',
            }
        }).encode('utf-8')
        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                'Content-Type': 'application/json',
                'Connect-Protocol-Version': '1',
                'x-codeium-csrf-token': csrf,
            },
            method='POST',
        )
        ctx = self._ssl_ctx if scheme == 'https' else None

        with urllib.request.urlopen(req, context=ctx, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode('utf-8'))

    def _query_endpoint(self, scheme, port, csrf):
        return self._post_rpc(scheme, port, csrf, 'RetrieveUserQuotaSummary')

    def get(self):
        summary_data = None
        if self._cached_endpoint:
            try:
                summary_data = self._query_endpoint(*self._cached_endpoint)
            except Exception:
                self._cached_endpoint = None

        if summary_data is None:
            last_err = None
            for cand in self._discover_candidates():
                try:
                    summary_data = self._query_endpoint(*cand)
                    self._cached_endpoint = cand
                    break
                except Exception as exc:
                    last_err = exc
            if summary_data is None:
                raise RuntimeError(f'無法連線至 Antigravity RetrieveUserQuotaSummary: {last_err}')

        try:
            return self._parse_quota_summary_5h(summary_data)
        except Exception:
            # Fallback to GetUserStatus if summary structure is unexpected
            status_data = self._post_rpc(*self._cached_endpoint, 'GetUserStatus')
            return self._parse_user_status(status_data)

    @staticmethod
    def _format_reset(reset_str):
        if not reset_str:
            return '--'
        try:
            dt = datetime.fromisoformat(reset_str.replace('Z', '+00:00')).astimezone()
            return dt.strftime('%m/%d %H:%M')
        except Exception:
            return str(reset_str)[:14]

    @classmethod
    def _parse_quota_summary_5h(cls, data):
        groups = data.get('response', {}).get('groups', [])
        if not groups:
            raise RuntimeError('Antigravity RetrieveUserQuotaSummary 未回傳 groups 配額資訊。')

        gemini_info = None
        claude_info = None

        for g in groups:
            g_name = str(g.get('displayName') or '').lower()
            buckets = g.get('buckets') or []
            bucket_5h = None
            bucket_weekly = None
            for b in buckets:
                bid = str(b.get('bucketId') or '').lower()
                win = str(b.get('window') or '').lower()
                if win == '5h' or bid.endswith('-5h'):
                    bucket_5h = b
                elif win == 'weekly' or bid.endswith('-weekly'):
                    bucket_weekly = b

            if not bucket_5h:
                continue

            raw_5h = float(bucket_5h.get('remainingFraction', 0.0))
            disabled_5h = bool(bucket_5h.get('disabled', False))
            rst_5h = cls._format_reset(bucket_5h.get('resetTime'))

            raw_weekly = float(bucket_weekly.get('remainingFraction', 0.0)) if bucket_weekly else 1.0
            rst_weekly = cls._format_reset(bucket_weekly.get('resetTime')) if bucket_weekly else rst_5h

            weekly_exhausted = disabled_5h or (bucket_weekly is not None and raw_weekly <= 0.0)
            five_h_exhausted = (not weekly_exhausted) and (raw_5h <= 0.0)

            if weekly_exhausted:
                frac = 0.0
                active_reset = rst_weekly
                display_str = rst_weekly
            elif five_h_exhausted:
                frac = 0.0
                active_reset = rst_5h
                display_str = rst_5h
            else:
                frac = max(0.0, min(1.0, raw_5h))
                active_reset = rst_5h
                display_str = f"{frac * 100:.1f}%"

            pct = max(0, min(100, int(round(frac * 100))))
            entry = {
                'pct': pct,
                'frac': frac,
                'raw_5h': raw_5h,
                'raw_weekly': raw_weekly,
                'weekly_exhausted': weekly_exhausted,
                'reset': active_reset,
                'reset_5h': rst_5h,
                'reset_weekly': rst_weekly,
                'display_str': display_str,
                'bucket_id': bucket_5h.get('bucketId'),
            }

            if 'gemini' in g_name or 'gemini' in str(bucket_5h.get('bucketId') or '').lower():
                gemini_info = entry
            elif 'claude' in g_name or 'gpt' in g_name or '3p' in str(bucket_5h.get('bucketId') or '').lower():
                claude_info = entry

        if not gemini_info and not claude_info:
            raise RuntimeError('找不到 5h 配額分桶 (gemini-5h / 3p-5h)。')

        g_frac = gemini_info['frac'] if gemini_info else 1.0
        c_frac = claude_info['frac'] if claude_info else 0.0
        g_pct = gemini_info['pct'] if gemini_info else 100
        c_pct = claude_info['pct'] if claude_info else 0
        g_str = gemini_info['display_str'] if gemini_info else f"{g_frac * 100:.1f}%"
        c_str = claude_info['display_str'] if claude_info else f"{c_frac * 100:.1f}%"

        return {
            'tier': '5H_LIMIT',
            'window': '5h',
            'quota_left': c_pct,
            'daily_left': c_pct,
            'claude_left': c_pct,
            'gpt_left': c_pct,
            'gemini_left': g_pct,
            'claude_frac': c_frac,
            'gemini_frac': g_frac,
            'claude_str': c_str,
            'gemini_str': g_str,
            'reset': claude_info['reset'] if claude_info else '--',
            'gemini_reset': gemini_info['reset'] if gemini_info else '--',
        }

    @classmethod
    def _parse_user_status(cls, data):
        configs = (
            data.get('userStatus', {})
            .get('cascadeModelConfigData', {})
            .get('clientModelConfigs', [])
        )
        if not configs:
            raise RuntimeError('Antigravity 未回傳 clientModelConfigs 配額資訊。')

        claude_info = None
        gpt_info = None
        gemini_info = None

        for c in configs:
            label = str(c.get('label') or '').lower()
            model_id = str(c.get('modelId') or '').lower()
            q = c.get('quotaInfo') or {}
            if 'remainingFraction' in q:
                frac = float(q['remainingFraction'])
            elif 'resetTime' in q:
                # Proto3 omits 0.0 float values in JSON when quota reaches 0%
                frac = 0.0
            else:
                continue

            pct = max(0, min(100, int(round(frac * 100))))
            rst = cls._format_reset(q.get('resetTime'))
            entry = {'pct': pct, 'frac': frac, 'reset': rst, 'label': c.get('label')}

            if ('claude' in label or 'claude' in model_id) and claude_info is None:
                claude_info = entry
            elif ('gpt' in label or 'gpt' in model_id) and gpt_info is None:
                gpt_info = entry
            elif ('gemini' in label or 'gemini' in model_id) and gemini_info is None:
                gemini_info = entry

        primary = claude_info or gpt_info
        if not primary:
            raise RuntimeError('Antigravity 配額清單中找不到 Claude / GPT 模型。')

        claude_pct = claude_info['pct'] if claude_info else primary['pct']
        gpt_pct = gpt_info['pct'] if gpt_info else primary['pct']
        gemini_pct = gemini_info['pct'] if gemini_info else 100

        claude_frac = claude_info['frac'] if claude_info else (primary['frac'] if primary else 0.0)
        gemini_frac = gemini_info['frac'] if gemini_info else 1.0

        return {
            'tier': 'CLAUDE/GPT',
            'quota_left': primary['pct'],
            'daily_left': primary['pct'],
            'claude_left': claude_pct,
            'gpt_left': gpt_pct,
            'gemini_left': gemini_pct,
            'claude_frac': claude_frac,
            'gemini_frac': gemini_frac,
            'claude_str': f"{claude_frac * 100:.1f}%",
            'gemini_str': f"{gemini_frac * 100:.1f}%",
            'reset': primary['reset'],
            'gemini_reset': gemini_info['reset'] if gemini_info else '--',
        }

