# meister-jamjam-back

마이스터 잼잼이 백엔드 (FastAPI). 개발 계획과 구조는 [CLAUDE.md](CLAUDE.md), API 명세는 노션 `[API]` 페이지를 따른다.

## 실행

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env
.venv/bin/uvicorn app.main:app --reload     # http://localhost:8000/docs
```

기본값은 SQLite라 DB 설치 없이 실행된다. 첫 실행에 테이블과 기본 데이터가 만들어진다.

## 테스트

```bash
.venv/bin/pytest
```

## 사전 등록 명단

로그인은 학교 구글 계정만 되고, 명단에 있는 이메일만 들어올 수 있다. CSV 형식은 `scripts/import_roster.py` 상단 주석을 본다.

```bash
.venv/bin/python -m scripts.import_roster roster.csv
```

## 기준 데이터

평가항목, 환산 등급, 상벌점 기준, 학사 일정, 테마 배경 갤러리, 대회 태그는 JSON으로 가져온다. 형식은 `scripts/reference.example.json`을 본다. 이미 있는 항목은 건너뛰고, 잘못된 값이 있으면 저장하지 않는다.

```bash
.venv/bin/python -m scripts.import_reference reference.json
```

운영에서는 처음 실행 전에 `SEED_ON_STARTUP=false`로 두어 예시 시드가 먼저 들어가지 않게 한다.
