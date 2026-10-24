"""Cloudflare R2 동기화 — data/lcf ↔ R2 버킷의 lcf/ 폴더 (public-api-monitor의 pam/과 같은 버킷을 써도 겹치지 않음)

  python -m lcf sync pull [--all-days]   state/ days/(최근 400일) feed/(최근 30일) digest/ status.json 받기
  python -m lcf sync push     바뀐 파일 올림 (site/에서 사라진 파일은 R2에서도 지움)
  python -m lcf sync ls       용량 보기

환경변수: R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET
"""
import datetime as dt, hashlib, os, re, sys
from concurrent.futures import ThreadPoolExecutor

from .core import DATA, log, today

PREFIX = "lcf/"


def client():
    need = ["R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET"]
    miss = [k for k in need if not os.environ.get(k)]
    if miss:
        sys.exit("R2 설정이 없습니다: " + ", ".join(miss))
    m = re.search(r"([0-9a-f]{32})", os.environ["R2_ACCOUNT_ID"])
    if not m:
        sys.exit("R2_ACCOUNT_ID 형식이 이상합니다 (32자리 16진수)")
    import boto3
    from botocore.config import Config
    s3 = boto3.client("s3", endpoint_url=f"https://{m.group(1)}.r2.cloudflarestorage.com",
                      aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"], aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
                      region_name="auto", config=Config(retries={"max_attempts": 5, "mode": "standard"}, max_pool_connections=16))
    return s3, os.environ["R2_BUCKET"]


def remote(s3, b):
    out, tok = {}, None
    while True:
        r = s3.list_objects_v2(Bucket=b, Prefix=PREFIX, **({"ContinuationToken": tok} if tok else {}))
        for o in r.get("Contents", []):
            out[o["Key"][len(PREFIX):]] = (o["Size"], o["ETag"].strip('"'))
        if not r.get("IsTruncated"):
            return out
        tok = r["NextContinuationToken"]


def _md5(p):
    h = hashlib.md5()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def _same(p, sz, etag):
    return p.exists() and p.stat().st_size == sz and ("-" in etag or _md5(p) == etag)


def _wanted(rel, all_days=False):
    if rel.startswith(("state/", "digest/")) or rel == "status.json":
        return True
    m = re.match(r"(days|feed)/(\d{4}-\d{2}-\d{2})\.json$", rel)
    if not m:
        return False
    if all_days and m.group(1) == "days":
        return True
    keep = 400 if m.group(1) == "days" else 30
    return m.group(2) >= (today() - dt.timedelta(days=keep)).isoformat()


def pull(all_days=False):
    s3, b = client()
    rem = remote(s3, b)
    todo = [k for k, (sz, et) in rem.items() if _wanted(k, all_days) and not _same(DATA / k, sz, et)]

    def get(k):
        (DATA / k).parent.mkdir(parents=True, exist_ok=True)
        s3.download_file(b, PREFIX + k, str(DATA / k))
    with ThreadPoolExecutor(16) as ex:
        list(ex.map(get, todo))
    log(f"R2에서 받음 {len(todo)}개")


def push():
    s3, b = client()
    rem = remote(s3, b)
    loc = {p.relative_to(DATA).as_posix(): p for p in DATA.rglob("*") if p.is_file() and not p.name.endswith(".tmp")}
    todo = [(rel, p) for rel, p in loc.items() if not (rel in rem and _same(p, *rem[rel]))]

    def put(j):
        ct = {"json": "application/json", "html": "text/html; charset=utf-8"}.get(j[0].rsplit(".", 1)[-1])
        s3.upload_file(str(j[1]), b, PREFIX + j[0], ExtraArgs={"ContentType": ct} if ct else None)
    with ThreadPoolExecutor(16) as ex:
        list(ex.map(put, todo))
    gone = [k for k in rem if k.startswith("site/") and k not in loc]
    for i in range(0, len(gone), 1000):
        s3.delete_objects(Bucket=b, Delete={"Objects": [{"Key": PREFIX + k} for k in gone[i:i + 1000]]})
    log(f"R2에 올림 {len(todo)}개" + (f" · 지움 {len(gone)}개" if gone else ""))


def put(rels):
    """지정한 파일만 올림 (data/lcf 기준 경로). push와 달리 다른 파일을 지우지 않음"""
    s3, b = client()
    for rel in rels:
        ct = {"json": "application/json", "tsv": "text/tab-separated-values; charset=utf-8", "txt": "text/plain; charset=utf-8"}.get(rel.rsplit(".", 1)[-1])
        s3.upload_file(str(DATA / rel), b, PREFIX + rel, ExtraArgs={"ContentType": ct} if ct else None)
        log(f"R2에 올림: {rel}")


def ls():
    s3, b = client()
    rem = remote(s3, b)
    top = {}
    for k, (sz, _) in rem.items():
        top[k.split("/")[0]] = top.get(k.split("/")[0], 0) + sz
    for k, v in sorted(top.items(), key=lambda x: -x[1]):
        print(f"  {k:<10} {v / 1e6:>9,.1f}MB")
    print(f"  합계 {len(rem)}개 · {sum(v[0] for v in rem.values()) / 1e6:,.1f}MB")
