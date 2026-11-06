import os, sys, json, re, time, base64, shutil, threading, subprocess, webbrowser, socket, secrets, string, glob
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
try:
    import webview
except Exception:
    webview = None

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0'
W = {'main': None, 'web': None}
LOCAL = ''
APPDIR = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'ChromeServerWizard')
os.makedirs(APPDIR, exist_ok=True)
SF = os.path.join(APPDIR, 'state.json')
ST = {'mail': '', 'ip': '', 'key': '', 'link': '', 'pw': '', 'ad_id': '', 'step': '0', 'done': '', 'ver': ''}
try:
    ST.update(json.load(open(SF, encoding='utf-8')))
except Exception:
    pass
if ST.get('ver') != '3':
    ST['step'], ST['done'], ST['ver'] = '0', '', '3'
if not ST['pw']:
    ST['pw'] = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(14))
NW = 0x08000000 if os.name == 'nt' else 0
J = {'lines': [], 'running': False, 'code': None}
LAST = {'ping': 0}


def save():
    try:
        json.dump(ST, open(SF, 'w', encoding='utf-8'), ensure_ascii=False)
    except Exception:
        pass


def log(s):
    J['lines'].append(s)


def ssh_base():
    return ['ssh', '-i', ST['key'], '-o', 'StrictHostKeyChecking=accept-new', '-o', 'ServerAliveInterval=20',
            '-o', 'ConnectTimeout=25', '-o', 'BatchMode=yes', 'ubuntu@' + ST['ip']]


def run_remote(script):
    b = base64.b64encode(script.encode()).decode()
    p = subprocess.Popen(ssh_base() + ['bash <(echo %s | base64 -d) </dev/null 2>&1' % b], stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, creationflags=NW, encoding='utf-8', errors='replace')
    for line in p.stdout:
        line = line.rstrip()
        m = re.match(r'^ANYDESK_ID=(\d{6,})$', line)
        if m:
            ST['ad_id'] = m.group(1)
        log(line)
    return p.wait()


def ssh_ok():
    try:
        return subprocess.run(ssh_base() + ['echo ok'], capture_output=True, timeout=45, creationflags=NW).returncode == 0
    except Exception:
        return False


APT = 'sudo DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a apt-get -o DPkg::Lock::Timeout=300 '
S_DESK = 'set -e\n' + APT + 'update\n' + APT + 'install -y xorg xfce4 lightdm dbus-x11 xserver-xorg-video-dummy pulseaudio pulseaudio-utils alsa-utils pavucontrol xfce4-pulseaudio-plugin fonts-noto-core fonts-liberation\nsudo systemctl set-default graphical.target'
S_CHR = 'set -e\nsudo snap install chromium'
S_AUTO = r"""set -e
sudo mkdir -p /etc/lightdm/lightdm.conf.d /etc/X11/xorg.conf.d
printf '[Seat:*]\nautologin-user=ubuntu\nautologin-user-timeout=0\nautologin-session=xfce\n' | sudo tee /etc/lightdm/lightdm.conf.d/50-autologin.conf >/dev/null
sudo tee /etc/X11/xorg.conf.d/10-dummy.conf >/dev/null <<'EOF'
Section "Monitor"
  Identifier "m"
  HorizSync 5.0-1000.0
  VertRefresh 5.0-200.0
  Modeline "1920x1080" 148.50 1920 2008 2052 2200 1080 1084 1089 1125 +hsync +vsync
EndSection
Section "Device"
  Identifier "d"
  Driver "dummy"
  VideoRam 256000
EndSection
Section "Screen"
  Identifier "s"
  Device "d"
  Monitor "m"
  DefaultDepth 24
  SubSection "Display"
    Depth 24
    Modes "1920x1080"
  EndSubSection
EndSection
EOF
sudo usermod -aG audio,video ubuntu
mkdir -p ~/.config/pulse ~/.config/autostart
printf '.include /etc/pulse/default.pa\nload-module module-null-sink sink_name=virtual_speaker sink_properties=device.description=VirtualSpeaker\nset-default-sink virtual_speaker\n' > ~/.config/pulse/default.pa
printf '[Desktop Entry]\nType=Application\nName=PulseAudio\nExec=pulseaudio --start\n' > ~/.config/autostart/pulseaudio.desktop
sudo systemctl enable lightdm
echo AUDIO_OK"""

S_ADI = r"""set -e
URL="LINKHERE"
if [ -z "$URL" ]; then URL=$(curl -fsSL https://anydesk.com/en/downloads/linux 2>/dev/null | grep -oE 'https://download\.anydesk\.com/[^" ]*arm64\.deb' | head -1 || true); fi
if [ -z "$URL" ]; then F=$(curl -fsSL https://download.anydesk.com/rpi/ 2>/dev/null | grep -oE 'anydesk_[0-9.]+-[0-9]+_arm64\.deb' | sort -uV | tail -1 || true); if [ -n "$F" ]; then URL="https://download.anydesk.com/rpi/$F"; fi; fi
if [ -z "$URL" ]; then echo NO_LINK; exit 3; fi
wget -q -O anydesk.deb "$URL"
""" + APT + 'install -y ./anydesk.deb'
S_ADB = r"""set -e
sudo systemctl enable anydesk
mkdir -p ~/.config/autostart
printf '[Desktop Entry]\nType=Application\nName=AnyDesk\nExec=anydesk --tray\n' > ~/.config/autostart/anydesk.desktop
nohup bash -c 'sleep 3; sudo reboot' >/dev/null 2>&1 &"""
S_ADP = r"""ID=""
for i in $(seq 1 15); do ID=$(anydesk --get-id 2>/dev/null | tail -n1); case "$ID" in ''|*[!0-9]*) sleep 6;; *) break;; esac; done
echo "PWHERE" | sudo anydesk --set-password
echo "ANYDESK_ID=$ID" """


def check_base():
    if not shutil.which('ssh'):
        log('לא נמצא ssh. הגדרות > אפליקציות > תכונות אופציונליות > OpenSSH Client')
        return False
    if not re.match(r'^\d{1,3}(\.\d{1,3}){3}$', ST['ip']) or not os.path.isfile(ST['key']):
        log('חסרים IP תקין או קובץ מפתח')
        return False
    if os.name == 'nt':
        subprocess.run(['icacls', ST['key'], '/inheritance:r', '/grant:r', os.environ.get('USERNAME', '') + ':R'],
                       capture_output=True, creationflags=NW)
    return True


def j_connect():
    if not check_base():
        return 1
    return run_remote('echo "מחובר כ: $(whoami)"')


def j_all():
    if not check_base():
        return 1
    for n, sc in ((1, S_DESK), (2, S_CHR), (3, S_AUTO)):
        log('##%d' % n)
        if run_remote(sc):
            return 1
    log('##4')
    link = ST['link'] if re.match(r'^https://[^\s"\']+$', ST['link']) else ''
    c = run_remote(S_ADI.replace('LINKHERE', link))
    if c:
        return c
    log('##5')
    if run_remote(S_ADB):
        return 1
    time.sleep(45)
    for _ in range(25):
        if ssh_ok():
            break
        time.sleep(8)
    else:
        return 1
    log('##6')
    c = run_remote(S_ADP.replace('PWHERE', ST['pw']))
    return c if c else (0 if ST['ad_id'] else 1)


JOBS = {'connect': j_connect, 'all': j_all}


def job_thread(name):
    try:
        J['code'] = JOBS[name]()
    except Exception as e:
        log('שגיאה: ' + str(e))
        J['code'] = 1
    save()
    J['running'] = False


def find_key():
    home, fs = os.path.expanduser('~'), []
    for d in ('Downloads', 'Desktop', 'Documents'):
        fs += glob.glob(os.path.join(home, d, '*.key'))
    fs = [f for f in fs if time.time() - os.path.getmtime(f) < 14 * 86400]
    return max(fs, key=os.path.getmtime) if fs else ''


def find_anydesk():
    for p in (r'C:\Program Files (x86)\AnyDesk\AnyDesk.exe', r'C:\Program Files\AnyDesk\AnyDesk.exe'):
        if os.path.isfile(p):
            return p
    home, fs = os.path.expanduser('~'), []
    for d in ('Downloads', 'Desktop'):
        fs += glob.glob(os.path.join(home, d, 'AnyDesk*.exe'))
    return max(fs, key=os.path.getmtime) if fs else ''


def launch_ad():
    if not ST['ad_id']:
        return 'עדיין אין ID. חזור לשלב ההתקנה.'
    exe = find_anydesk()
    if not exe:
        return 'לא נמצא AnyDesk. הורד אותו קודם.'
    p = subprocess.Popen([exe, ST['ad_id'], '--with-password'], stdin=subprocess.PIPE)
    p.stdin.write((ST['pw'] + '\n').encode())
    p.stdin.close()
    return ''


def clip():
    try:
        import tkinter as tk
        r = tk.Tk()
        r.withdraw()
        t = r.clipboard_get()
        r.destroy()
        return t or ''
    except Exception:
        return ''


def pick():
    if webview and W['main']:
        try:
            kind = webview.FileDialog.OPEN if hasattr(webview, 'FileDialog') else webview.OPEN_DIALOG
            r = W['main'].create_file_dialog(kind, directory=os.path.join(os.path.expanduser('~'), 'Downloads'))
            return os.path.normpath(r[0]) if r else ''
        except Exception:
            pass
    import tkinter as tk
    from tkinter import filedialog
    r = tk.Tk()
    r.withdraw()
    r.attributes('-topmost', True)
    p = filedialog.askopenfilename(title='קובץ המפתח (.key)')
    r.destroy()
    return os.path.normpath(p) if p else ''


def find_chrome():
    for b in (os.environ.get('PROGRAMFILES', ''), os.environ.get('PROGRAMFILES(X86)', ''), os.environ.get('LOCALAPPDATA', '')):
        if b:
            p = os.path.join(b, 'Google', 'Chrome', 'Application', 'chrome.exe')
            if os.path.isfile(p):
                return p
    return shutil.which('chrome') or shutil.which('google-chrome')


def open_chrome_profiles():
    c = find_chrome()
    if c:
        subprocess.Popen([c, '--profile-picker'])
    else:
        webbrowser.open('https://mail.google.com/')


def clip_fast():
    if os.name != 'nt':
        return clip()
    import ctypes
    from ctypes import wintypes
    u, k = ctypes.windll.user32, ctypes.windll.kernel32
    u.OpenClipboard.argtypes = [wintypes.HWND]
    u.OpenClipboard.restype = wintypes.BOOL
    u.GetClipboardData.argtypes = [wintypes.UINT]
    u.GetClipboardData.restype = wintypes.HANDLE
    k.GlobalLock.argtypes = [wintypes.HGLOBAL]
    k.GlobalLock.restype = ctypes.c_void_p
    k.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    if not u.OpenClipboard(None):
        return ''
    try:
        h = u.GetClipboardData(13)
        if not h:
            return ''
        ptr = k.GlobalLock(h)
        if not ptr:
            return ''
        try:
            return ctypes.wstring_at(ptr)
        finally:
            k.GlobalUnlock(h)
    finally:
        u.CloseClipboard()


def unwrap_link(t):
    p = urlparse(t)
    if 'google.' in p.netloc.lower() and p.path == '/url':
        q = parse_qs(p.query)
        v = (q.get('q') or q.get('url') or [''])[0]
        if v.startswith('https://'):
            return v
    return t


def front(w):
    try:
        w.restore()
        w.on_top = True
        w.on_top = False
    except Exception:
        pass


def web_closed():
    W['web'] = None


def open_web(url, title='Oracle'):
    """פותח את הקישור בחלון נפרד, והאשף נשאר פתוח."""
    if not (webview and W['main']):
        webbrowser.open(url)
        return 0
    if W['web']:
        try:
            W['web'].load_url(url)
            front(W['web'])
            return 1
        except Exception:
            W['web'] = None
    w = webview.create_window(title, url, width=1100, height=850)
    w.events.closed += web_closed
    W['web'] = w
    return 1


def clip_watch():
    """כשמעתיקים קישור של Oracle מהמייל, הוא נפתח אוטומטית בחלון נפרד."""
    try:
        last = clip_fast().strip()
    except Exception:
        last = ''
    while True:
        time.sleep(1)
        try:
            t = clip_fast().strip()
            if not t or t == last:
                continue
            last = t
            if not re.match(r'^https://\S+$', t):
                continue
            t = unwrap_link(t)
            if 'oracle' in urlparse(t).netloc.lower():
                open_web(t)
        except Exception:
            pass


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, obj, ctype='application/json'):
        b = obj if isinstance(obj, bytes) else json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', ctype + '; charset=utf-8')
        self.send_header('Content-Length', str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == '/':
            return self.send(HTML.encode('utf-8'), 'text/html')
        if u.path == '/api/ping':
            LAST['ping'] = time.time()
            return self.send({'ok': 1})
        if u.path == '/api/state':
            return self.send(ST)
        if u.path == '/api/findkey':
            return self.send({'path': find_key()})
        if u.path == '/api/log':
            n = int(parse_qs(u.query).get('from', ['0'])[0])
            ls = J['lines'][n:]
            return self.send({'lines': ls, 'n': n + len(ls), 'done': not J['running'], 'code': J['code'], 'state': {'ad_id': ST['ad_id']}})
        self.send({})

    def do_POST(self):
        d = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))) or b'{}')
        p = urlparse(self.path).path
        if p == '/api/state':
            for k in ST:
                if k in d:
                    ST[k] = str(d[k]).strip()
            save()
            return self.send({'ok': 1})
        if p == '/api/browse':
            url = str(d.get('url', ''))
            if not url.startswith('https://'):
                return self.send({})
            if d.get('external'):
                webbrowser.open(url)
                return self.send({'embedded': 0})
            return self.send({'embedded': open_web(url)})
        if p == '/api/chrome':
            open_chrome_profiles()
            return self.send({'ok': 1})
        if p == '/api/clip':
            return self.send({'text': clip()})
        if p == '/api/pick':
            return self.send({'path': pick()})
        if p == '/api/launch':
            return self.send({'error': launch_ad()})
        if p == '/api/run':
            if J['running']:
                return self.send({'error': 'busy'})
            if d.get('job') not in JOBS:
                return self.send({'error': '?'})
            J.update(lines=[], running=True, code=None)
            threading.Thread(target=job_thread, args=(d['job'],), daemon=True).start()
            return self.send({'ok': 1})
        self.send({})


def find_browser():
    pf = [os.environ.get('PROGRAMFILES(X86)', ''), os.environ.get('PROGRAMFILES', ''), os.environ.get('LOCALAPPDATA', '')]
    for rel in (r'Microsoft\Edge\Application\msedge.exe', r'Google\Chrome\Application\chrome.exe'):
        for b in pf:
            if b and os.path.isfile(os.path.join(b, rel)):
                return os.path.join(b, rel)
    return shutil.which('msedge') or shutil.which('chrome') or shutil.which('google-chrome')


def main():
    global LOCAL
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    srv = ThreadingHTTPServer(('127.0.0.1', port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    LOCAL = 'http://127.0.0.1:%d/' % port
    if webview:
        try:
            webview.settings['ALLOW_DOWNLOADS'] = True
        except Exception:
            pass
        w = webview.create_window('כרום על שרת חינמי', LOCAL, width=1200, height=850, min_size=(900, 650))
        W['main'] = w
        w.events.closed += lambda: os._exit(0)
        threading.Thread(target=clip_watch, daemon=True).start()
        try:
            webview.start(user_agent=UA, private_mode=False, storage_path=os.path.join(APPDIR, 'webview'))
        except TypeError:
            webview.start()
        return
    br = find_browser()
    if br:
        subprocess.Popen([br, '--app=' + LOCAL, '--window-size=1100,820'])
    else:
        webbrowser.open(LOCAL)
    t0 = time.time()
    while True:
        time.sleep(3)
        if LAST['ping'] and time.time() - LAST['ping'] > 90 and not J['running']:
            break
        if not LAST['ping'] and time.time() - t0 > 60:
            break


HTML = r"""<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8"><title>כרום על שרת חינמי</title>
<style>
:root{--ac:#0f766e;--ac2:#115e59;--tx:#0f172a;--mu:#64748b;--bd:#e2e8f0;--bg:#f8fafc}*{box-sizing:border-box}
body{margin:0;height:100vh;display:flex;font-family:"Segoe UI Variable","Segoe UI",Arial,sans-serif;background:var(--bg);color:var(--tx)}
aside{width:260px;background:#fff;border-inline-end:1px solid var(--bd);padding:34px 26px}
.brand{font-weight:700;font-size:17px;margin-bottom:34px}.brand small{display:block;font-weight:400;color:var(--mu);font-size:13px;margin-top:4px}
.st{display:flex;align-items:center;gap:14px;padding:9px 0;cursor:pointer;color:var(--mu);font-size:15px;position:relative}
.st b{width:26px;height:26px;border-radius:50%;border:1.5px solid var(--bd);display:grid;place-items:center;font-size:12px;font-weight:600;background:#fff;z-index:1}
.st:not(:last-child)::after{content:"";position:absolute;right:12px;top:35px;height:18px;width:1.5px;background:var(--bd)}
.st.on{color:var(--tx);font-weight:600}.st.on b{border-color:var(--ac);background:var(--ac);color:#fff}.st.ok b{border-color:var(--ac);color:var(--ac)}
.pane{flex:1;display:flex;flex-direction:column;min-width:0}
main{flex:1;display:flex;align-items:center;padding:40px 72px;overflow:auto}
.card{width:100%;max-width:540px;animation:in .3s}@keyframes in{from{opacity:0;transform:translateY(8px)}}
.n{font-size:13px;color:var(--ac);font-weight:600;margin-bottom:10px}
h2{margin:0 0 10px;font-size:34px;font-weight:700;letter-spacing:-.3px}.sub{font-size:17px;color:var(--mu);margin:0 0 28px;line-height:1.6}
.row{display:flex;gap:12px;flex-wrap:wrap}
.btn{padding:13px 28px;border:0;border-radius:10px;background:var(--ac);color:#fff;font:600 16px inherit;font-family:inherit;cursor:pointer;transition:.15s;box-shadow:0 1px 2px #0f172a22}
.btn:hover{background:var(--ac2)}.btn:disabled{opacity:.55;cursor:default}.btn.alt{background:#fff;color:var(--tx);border:1px solid var(--bd);box-shadow:none}.btn.alt:hover{background:var(--bg)}
.in{width:100%;padding:13px 16px;font-size:18px;border:1px solid var(--bd);border-radius:10px;direction:ltr;text-align:left;outline:0;background:#fff;font-family:Consolas,monospace}.in:focus{border-color:var(--ac);box-shadow:0 0 0 3px #0f766e22}
.kr{display:flex;justify-content:space-between;align-items:center;border:1px solid var(--bd);background:#fff;border-radius:10px;padding:10px 16px;margin:12px 0 24px;font-size:15px;color:var(--mu)}
.kr button,.cp{border:0;background:none;color:var(--ac);font:600 14px inherit;font-family:inherit;cursor:pointer}
.msg{min-height:24px;margin:0 0 14px;font-size:15px;color:var(--mu)}
.chk{list-style:none;padding:0;margin:0 0 18px;border:1px solid var(--bd);border-radius:12px;background:#fff}
.chk li{display:flex;align-items:center;gap:12px;padding:11px 16px;font-size:15px;color:var(--mu)}.chk li+li{border-top:1px solid var(--bd)}
.chk i{width:18px;height:18px;border-radius:50%;border:2px solid var(--bd);flex:none}.chk .run{color:var(--tx)}
.chk .run i{border-color:var(--ac);border-top-color:transparent;animation:sp .8s linear infinite}@keyframes sp{to{transform:rotate(360deg)}}
.chk .ok{color:var(--tx)}.chk .ok i{background:var(--ac);border-color:var(--ac);position:relative}.chk .ok i::after{content:"";position:absolute;left:4px;top:1px;width:4px;height:8px;border:solid #fff;border-width:0 2px 2px 0;transform:rotate(45deg)}
.bar{height:4px;background:var(--bd);border-radius:2px;margin-bottom:18px;overflow:hidden}.bar i{display:block;height:100%;background:var(--ac);width:0;transition:.5s}
.cred{border:1px solid var(--bd);border-radius:12px;background:#fff;margin-top:26px}.cred div{display:flex;align-items:center;gap:12px;padding:12px 16px;font-size:15px}.cred div+div{border-top:1px solid var(--bd)}
.cred span{color:var(--mu);width:60px}.cred b{flex:1;direction:ltr;text-align:left;font-family:Consolas,monospace;font-weight:500}
ul.ht{margin:0 0 22px;padding:0 20px;color:var(--mu);line-height:1.9;font-size:15px}
details{margin-top:14px;font-size:14px;color:var(--mu)}.log{background:#0f172a;color:#cbd5e1;direction:ltr;text-align:left;padding:12px;border-radius:10px;height:150px;overflow:auto;font:12px Consolas,monospace;white-space:pre-wrap}
.foot{display:flex;justify-content:space-between;align-items:center;padding:16px 72px;border-top:1px solid var(--bd);background:#fff}
.foot button{border:0;background:none;font:600 15px inherit;font-family:inherit;color:var(--mu);cursor:pointer;padding:8px 4px}.foot button:hover{color:var(--tx)}.foot .nx{color:var(--ac)}.foot div{display:flex;gap:26px}
</style></head><body>
<aside><div class="brand">כרום על שרת חינמי<small>אשף התקנה</small></div><div id="side"></div></aside>
<div class="pane"><main><div class="card" id="card"></div></main>
<div class="foot"><button onclick="go(cur-1)" id="prev">הקודם</button><div><button class="nx" onclick="nxt()" id="next">הבא</button><button onclick="go(cur+1)" id="skip">דלג</button></div></div></div>
<script>
const $=s=>document.querySelector(s),sleep=ms=>new Promise(r=>setTimeout(r,ms));
const api=(p,b)=>fetch('/api/'+p,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b||{})}).then(r=>r.json());
const esc=s=>String(s==null?'':s).replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;');
let S={mail:'',ip:'',key:'',link:'',pw:'',ad_id:'',step:'0',done:'',ver:''},cur=0,D=new Set(),busy=false,LOG='',PR={},MSG='',NL=false,FK=false;
const IT=['שולחן עבודה','דפדפן','מסך וירטואלי','AnyDesk','הפעלה מחדש','קוד וסיסמה'];
const FUNS=['','מתקין שולחן עבודה…','מתקין דפדפן…','מגדיר מסך וירטואלי…','מתקין AnyDesk…','ממתין לאתחול השרת…','מגדיר קוד וסיסמה…'];
const HT={1:['לחץ Start for free','אזור: Frankfurt או Amsterdam','כרטיס אשראי לאימות בלבד, ללא חיוב'],3:['Create instance · שם: chrome','Image: Ubuntu 22.04 (לא Minimal)','Shape: Ampere · A1.Flex · 4 OCPU · 24GB','SSH keys: Generate + Save private key','בסיום: העתק את ה-Public IP'],5:['בחר DEB · ARM 64-bit','קליק ימני > Copy link address'],6:['לחץ Download Now','לאחר ההורדה: חזרה לאשף']};
const hints=n=>HT[n]?`<ul class="ht">${HT[n].map(x=>`<li>${x}</li>`).join('')}</ul>`:'';
const bb=(st,u,l,c)=>`<button class="btn ${c||''}" onclick="browse(${st},'${u}')">${l}</button> <button class="btn alt" onclick="browseExt(${st},'${u}')">בדפדפן הרגיל</button>`;
const cred=a=>`<div class="cred">${a.map(([l,v])=>`<div><span>${l}</span><b>${esc(v||'—')}</b>${v?`<button class="cp" onclick="navigator.clipboard.writeText('${esc(v)}')">העתק</button>`:''}</div>`).join('')}</div>`;
const chk=()=>IT.map((t,i)=>`<li class="${PR[i+1]||''}"><i></i>${t}</li>`).join('');
const STEPS=[
{t:'התחלה',h:()=>`<p class="sub">הקמת כרום על שרת חינמי. כ-20 דקות.</p><button class="btn" onclick="nxt()">התחל</button>`},
{t:'חשבון Oracle',h:()=>`<p class="sub">פתיחת חשבון חינמי ב-Oracle. החלון נפתח בנפרד והאשף נשאר פתוח.</p>${hints(1)}${bb(1,'https://signup.cloud.oracle.com/?source=:ow:o:p:feb:0916FreePageBannerButton&amp;intcmp=:ow:o:p:feb:0916FreePageBannerButton','פתח את Oracle')}<div class="msg" id="fun" style="margin-top:14px">${MSG}</div>`},
{t:'מייל',h:()=>`<p class="sub">Oracle שולחת קישור למייל. פתח את כרום, בחר פרופיל והיכנס למייל. כשתעתיק את הקישור (קליק ימני &gt; העתק כתובת קישור) הוא ייפתח כאן בתוכנה אוטומטית.</p><div class="row"><button class="btn" onclick="openMail()">פתח את כרום</button><button class="btn alt" onclick="pasteOpen()">הדבק ופתח</button></div><div class="msg" id="fun" style="margin-top:14px">${MSG}</div>`},
{t:'יצירת שרת',h:()=>`<p class="sub">יצירת שרת בקונסולת Oracle.</p>${hints(3)}${bb(3,'https://cloud.oracle.com/compute/instances','פתח את הקונסולה')}<div class="msg" id="fun" style="margin-top:14px">${MSG}</div>`},
{t:'פרטי השרת',h:()=>`<p class="sub">הזן את כתובת ה-IP של השרת.</p>
<input class="in" value="${esc(S.ip)}" placeholder="130.61.10.20" oninput="S.ip=this.value.trim()">
<div class="kr"><span>${S.key?esc(S.key.split(/[\\/]/).pop()):'קובץ מפתח: לא נמצא'}</span><button onclick="pick()">${S.key?'החלף':'בחר'}</button></div>
<div class="msg" id="fun">${MSG}</div><button class="btn act" onclick="run('connect')">בדוק חיבור</button>`},
{t:'התקנה',h:()=>`<p class="sub">ההתקנה רצה אוטומטית ולוקחת כמה דקות.</p><div class="bar"><i id="bar" style="width:${pct()}%"></i></div><ul class="chk" id="chk">${chk()}</ul><div class="msg" id="fun">${MSG}</div>
${NL?`<p class="sub" style="margin-bottom:12px">לא נמצא קישור אוטומטי. הדבק קישור DEB (ARM 64-bit).</p><input class="in" style="margin-bottom:14px" value="${esc(S.link)}" placeholder="https://download.anydesk.com/..." oninput="S.link=this.value.trim()">${bb(5,'https://anydesk.com/en/downloads/linux','פתח את AnyDesk','alt')}<br><br>`:''}${NL?hints(5):''}
<button class="btn act" onclick="run('all')">${busy?'מתקין…':'התחל התקנה'}</button><details><summary>פרטים טכניים</summary><pre class="log" id="lg">${esc(LOG)}</pre></details>`},
{t:'חיבור',h:()=>`<p class="sub">הורד את AnyDesk והתחבר לשרת.</p>${hints(6)}<div class="row">${bb(6,'https://anydesk.com/en/downloads/windows','הורד AnyDesk','alt')}<button class="btn act" onclick="launch()">התחבר לשרת</button></div><div class="msg" id="fun" style="margin-top:14px">${MSG}</div>${cred([['ID',S.ad_id],['סיסמה',S.pw]])}`},
{t:'סיום',h:()=>`<p class="sub">בשרת: תפריט יישומים &gt; Internet &gt; Chromium. הגלישה יוצאת מ-Oracle.</p><button class="btn" onclick="launch()">התחבר לשרת</button><div class="msg" id="fun" style="margin-top:14px">${MSG}</div>${cred([['IP',S.ip],['ID',S.ad_id],['סיסמה',S.pw]])}`}];
const pct=()=>Math.round(Object.values(PR).filter(x=>x=='ok').length/6*100);
function render(){
 $('#side').innerHTML=STEPS.map((s,i)=>`<div class="st ${i==cur?'on':''} ${D.has(i)&&i!=cur?'ok':''}" onclick="go(${i})"><b>${D.has(i)&&i!=cur?'✓':i+1}</b>${s.t}</div>`).join('');
 $('#card').innerHTML=`<div class="n">שלב ${cur+1} מתוך ${STEPS.length}</div><h2>${STEPS[cur].t}</h2>`+STEPS[cur].h();
 const last=cur==STEPS.length-1;$('#prev').style.visibility=cur?'visible':'hidden';$('#next').style.visibility=$('#skip').style.visibility=last?'hidden':'visible';
 document.querySelectorAll('.act').forEach(b=>b.disabled=busy);
 if(cur==4&&!S.key&&!FK){FK=true;fetch('/api/findkey').then(r=>r.json()).then(r=>{if(r.path){S.key=r.path;save();if(cur==4)render()}})}
}
function upd(){const c=$('#chk'),f=$('#fun'),l=$('#lg'),b=$('#bar');if(c)c.innerHTML=chk();if(f)f.textContent=MSG;if(b)b.style.width=pct()+'%';if(l){l.textContent=LOG;l.scrollTop=l.scrollHeight}}
const save=()=>{S.step=cur;S.done=[...D].join(',');return api('state',S)};
function go(i){if(i<0||i>=STEPS.length)return;save();cur=i;MSG='';render()}
function nxt(){D.add(cur);go(cur+1)}
async function browse(st,url){await save();await api('browse',{url,step:st});MSG='נפתח חלון נפרד. בסיום חזור לכאן ולחץ הבא';render()}
async function browseExt(st,url){await save();await api('browse',{url,step:st,external:1});MSG='נפתח בדפדפן הרגיל. בסיום חזור לכאן ולחץ הבא';render()}
async function openMail(){await api('chrome');MSG='נפתח בורר הפרופילים בכרום';render()}
async function pasteOpen(){const r=await api('clip'),u=(r.text||'').trim();if(!/^https:\/\/\S+$/.test(u)){MSG='לא נמצא קישור בלוח. העתק את הקישור מהמייל ונסה שוב';render();return}await browse(1,u)}
async function pick(){const r=await api('pick');if(r.path){S.key=r.path;await save();render()}}
async function launch(){const r=await api('launch');MSG=r.error||'מתחבר… ייתכן שיידרש אישור ב-AnyDesk';render()}
async function run(name){
 if(busy)return;if(!S.ip||!S.key){MSG='חסרים כתובת IP או קובץ מפתח';render();return}
 await save();busy=true;LOG='';PR={};NL=false;MSG=name=='connect'?'מתחבר…':FUNS[1];render();
 await api('run',{job:name});let n=0;
 while(true){await sleep(800);const d=await (await fetch('/api/log?from='+n)).json();n=d.n;
  d.lines.forEach(l=>{const m=l.match(/^##(\d)$/);if(m){const k=+m[1];for(let i=1;i<k;i++)PR[i]='ok';PR[k]='run';MSG=FUNS[k]}else{LOG+=l+'\n';if(l=='NO_LINK')NL=true}});
  S.ad_id=d.state.ad_id||S.ad_id;
  if(d.done){busy=false;const ok=d.code==0;
   if(ok){if(name=='all')for(let i=1;i<=6;i++)PR[i]='ok';MSG=name=='all'?'ההתקנה הסתיימה':'החיבור הצליח';D.add(cur);render();await save();await sleep(1200);go(cur+1)}
   else{MSG=NL?'':name=='connect'?'החיבור נכשל. בדוק IP וקובץ מפתח':'ההתקנה נכשלה. נסה שוב';render();save()}
   break}
  upd()}
}
fetch('/api/state').then(r=>r.json()).then(s=>{S=Object.assign(S,s);D=new Set((S.done||'').split(',').filter(x=>x!=='').map(Number));
 const q=new URLSearchParams(location.search);cur=q.has('step')?Math.min(+q.get('step'),STEPS.length-1):(+S.step||0);if(q.has('done'))D.add(+q.get('done'));
 history.replaceState(null,'','/');save();render()});
setInterval(()=>fetch('/api/ping'),5000);
</script></body></html>"""

if __name__ == '__main__':
    main()
