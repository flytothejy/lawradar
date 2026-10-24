"""공통 경로·로그·환경변수"""
import datetime as dt, json, os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "lcf"          # R2의 lcf/ 폴더와 1:1 (저장소에는 커밋하지 않음)
STATE = DATA / "state"                # 누적 상태 (본 항목, 시행 예정 목록)
DAYS = DATA / "days"                  # 공포·발령일 기준 날짜별 원본+보강 결과
FEED = DATA / "feed"                  # 수집한 날 기준 '새로 발견한 것' (알림의 근거)
DIGEST = DATA / "digest"              # 주간 다이제스트 결과
BRAND = "법레이더"                    # 서비스 이름 (화면·상세 페이지·알림)
SITE = DATA / "site"                  # 화면용 결과물 (Pages가 가져감)
CONFIG = ROOT / "config"
KST = dt.timezone(dt.timedelta(hours=9))


def now():
    return dt.datetime.now(KST)


def today():
    return now().date()


def ymd(d):
    return d.strftime("%Y%m%d")


def parse_ymd(s):
    s = str(s or "").strip()
    return dt.date(int(s[:4]), int(s[4:6]), int(s[6:8])) if len(s) >= 8 and s[:8].isdigit() else None


def log(*a):
    print(f"[{now():%H:%M:%S}]", *a, file=sys.stderr, flush=True)


def load_env():
    """PC에서 실행할 때 .env를 읽음 (Actions에서는 Secrets가 환경변수로 들어옴)"""
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def write_json(path, obj, pretty=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1 if pretty else None,
                              separators=None if pretty else (",", ":")), encoding="utf-8")
    tmp.replace(path)


def read_json(path, default=None):
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def config(name):
    return read_json(CONFIG / f"{name}.json", {})


def status(step, **kw):
    p = DATA / "status.json"
    s = read_json(p, {})
    s[step] = {"finished": now().isoformat(timespec="seconds"), **kw}
    write_json(p, s, pretty=True)
