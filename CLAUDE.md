# CLAUDE.md — 마이스터 잼잼이 백엔드

이 문서는 노션 [마이스터 잼잼이](https://app.notion.com/p/40762fa2a9998097bcaadb4df92a1194) 페이지(기능 명세, DB 설계, `[API]` 명세)를 바탕으로 정리한 **백엔드 개발 계획**이다. 이 저장소에서 작업할 때는 이 문서를 기준으로 하고, 세부 요청·응답 예시는 노션 `[API]` 페이지를 원본으로 삼는다.

---

## 1. 프로젝트 개요

- BSSM(부산소프트웨어마이스터고) 학생·교사용 서비스
- 핵심 기능: 마이스터 역량(마역량) 점수 랭킹·세부 조회·점수 부여(증빙 + AI 분석), 상벌점, 대회 정보·LLM 대회 추천, 자진 신고, 테마 커스텀, 핀볼·자리뽑기, 알림
- 사용자 역할: `STUDENT`(학생), `TEACHER`(교사), `ADMIN`(관리자 = 교사 권한 + 운영 설정)
- 로그인: 학교 구글 계정(`@bssm.hs.kr`)만 허용, 회원가입·비밀번호 로그인 없음

## 2. 기술 스택

| 구분 | 선택 | 비고 |
| --- | --- | --- |
| 웹 프레임워크 | FastAPI + Uvicorn | 현재 설치됨 |
| 설정 | pydantic-settings, python-dotenv | 현재 설치됨 (`.env.example`) |
| ORM / 마이그레이션 | SQLAlchemy 2.0(async) + Alembic | 구현됨 (`alembic/versions/0001_initial_schema.py`) |
| DB | 운영 MySQL 8(`aiomysql`) / 로컬·테스트 SQLite(`aiosqlite`) | UUID는 CHAR(36), ENUM은 VARCHAR로 저장해 둘 다 같게 동작 |
| 캐시·세션 | 인메모리(기본) → Redis | `app/common/kv.py`·`ratelimit.py`·`NotificationHub` 인터페이스 뒤에 두었다. 여러 서버로 운영하면 Redis 구현으로 교체 |
| 인증 | joserfc + httpx (Google OIDC, Authorization Code + PKCE) | 구현됨 (`domains/auth/oauth.py`) |
| 파일 저장 | 로컬 디스크(기본) → S3 호환 | `app/common/storage.py`. private(증빙·자진 신고 첨부) / public(테마 배경, `/media`로 서빙) |
| 이미지 | Pillow | GIF 썸네일. MP4 썸네일·오디오 제거는 ffmpeg가 있을 때만 |
| 암호화 | `cryptography` AES-256-GCM | 자진 신고 제목·내용·답변·첨부 |
| LLM / OCR | 미정 | 증빙 분석, 대회 추천·챗 |
| 테스트 | pytest, httpx(AsyncClient) | `tests/conftest.py` 있음 |

바꾸면 이 표를 함께 고친다.

## 3. 디렉터리 구조와 계층 규칙

```
app/
  main.py              # FastAPI 앱 생성, 미들웨어, 예외 핸들러 등록
  api.py               # 도메인 라우터 집계 (/api, /auth)
  core/
    config.py          # Settings (pydantic-settings)
    database.py        # 엔진·세션 생성
    dependencies.py    # get_db, get_current_user, require_role 등
    security.py        # 세션, Origin 검사, 암호화 유틸
  common/
    exceptions.py      # AppException + 오류 응답 형식
    pagination.py      # 페이지·커서 응답 모델
  domains/<domain>/
    router.py          # HTTP 입출력만 (검증·권한 의존성 연결)
    service.py         # 비즈니스 로직, 트랜잭션 경계
    repository.py      # DB 접근 (쿼리만)
    models.py          # SQLAlchemy 모델
    schemas.py         # 요청·응답 Pydantic 모델 (camelCase alias)
tests/
```

- 호출 방향은 `router → service → repository` 한 방향. router에서 repository를 직접 부르지 않는다.
- 요청 본문 스키마는 `schemas.py`에 두고, 응답은 camelCase dict로 service가 만든다 (응답 모델 클래스를 일일이 만들지 않는다).
- 도메인에 파일이 더 필요하면 추가한다 (예: `merit/evidence_router.py`·`evidence_service.py`·`analyzer.py`, `game/rng.py`·`seat.py`·`pinball.py`, `theme/media.py`, `user/links.py`).
- 트랜잭션은 service에서 연다. 점수 반영 + 내역 저장 + 알림 저장처럼 함께 바뀌는 것은 한 트랜잭션.
- 도메인 간 호출은 service끼리 한다 (예: merit service → notification service).

### 노션 기능 ↔ 도메인 매핑

| 도메인 | 담당 기능 (노션) |
| --- | --- |
| `auth` | 로그인 (`/auth/google*`, `/auth/logout`) |
| `user` | `/api/me`, 프로필 링크, 학생 기본 정보, 교사 검색, 학급 명단 |
| `merit` | 마역량 랭킹, 마역량 세부 조회, 마역량 점수 부여(평가항목·증빙·승인/반려·직접 부여), 환산 등급 기준 |
| `mileage` | 상벌점 기준 조회, 상·벌점 내역·부여 |
| `contest` | 대회 정보·카테고리·태그·북마크, 학사 일정 |
| `recommend` | 대회 추천 LLM, 추가 질의응답, 추천 가이드라인 |
| `report` | 자진 신고 |
| `theme` | 테마 커스텀 |
| `game` | 핀볼·자리뽑기, 공정성 검증 |
| `notification` | 알림 (**폴더 신규 추가 필요**) |

## 4. 공통 API 규칙 (노션 `[API] 공통 규칙`)

| 구분 | 규칙 |
| --- | --- |
| Base URL | `/api` (구글 로그인 흐름만 `/auth`) |
| 형식 | `application/json; charset=UTF-8`, 파일 업로드는 `multipart/form-data` |
| 필드 이름 | JSON은 camelCase, DB 컬럼은 snake_case → Pydantic `alias_generator=to_camel`, `populate_by_name=True` |
| 날짜·시간 | ISO 8601, 한국 시간 `+09:00` (날짜만은 `YYYY-MM-DD`) |
| 인증 | 세션 쿠키 `SESSION` (`HttpOnly`, `Secure`, `SameSite=Lax`, `Max-Age=604800`, 사용 시 갱신). `/auth/*` 외 전부 필요 |
| 출처 검사 | POST·PUT·PATCH·DELETE는 `Origin`이 서비스 도메인일 때만 처리 |
| ID | 사용자·학생·내역: UUID / 대회·태그·카테고리·평가항목·기준: 정수 AUTO_INCREMENT |

### 응답 형식

- 단건: 리소스 객체 그대로 (래퍼 없음)
- 페이지 목록: `{ "items": [], "page": 1, "size": 20, "totalElements": 0, "totalPages": 0 }`
- 커서 목록(알림 등): `{ "items": [], "nextCursor": "..." | null }`
- 오류: `{ "code": "VALIDATION_FAILED", "message": "화면에 그대로 보여 줄 문구", "fieldErrors": [{ "field", "reason", "message" }] }`
  - `message`에 스택·SQL 등 원인 상세를 넣지 않는다 (서버 로그에만)
  - `fieldErrors`는 입력 검증 실패일 때만
  - FastAPI 기본 422 대신 `400 VALIDATION_FAILED`로 변환하는 핸들러를 둔다

### 공통 상태 코드

| HTTP | code | 의미 |
| --- | --- | --- |
| 400 | `VALIDATION_FAILED` | 입력값 검증 실패 |
| 401 | `UNAUTHORIZED` | 비로그인·세션 만료 |
| 403 | `FORBIDDEN` | 권한 없음 |
| 404 | `NOT_FOUND` (기능별 `*_NOT_FOUND`) | 대상 없음. 권한 없는 비공개 자원도 404 |
| 409 | `CONFLICT` 계열 | 상태 충돌·중복 |
| 413 | `FILE_TOO_LARGE` | 파일 용량 초과 |
| 415 | `UNSUPPORTED_FILE_TYPE` | 허용되지 않은 파일 (확장자가 아니라 파일 내용으로 판별) |
| 429 | `TOO_MANY_REQUESTS` | 요청 과다, `Retry-After` 포함 |
| 500 | `INTERNAL_ERROR` | 서버 오류 |
| 502 | `UPSTREAM_ERROR` | 구글·LLM·OCR 오류·지연 |

### 요청 제한

| 대상 | 제한 |
| --- | --- |
| `/auth/google*` | IP당 분당 20회 |
| 상벌점 기준 조회 | IP당 분당 60회 |
| 프로필 링크 수정 | 사용자당 분당 20회 |
| 대회 추천 LLM | 사용자당 분당 10회, 하루 100회 |
| 파일 업로드 | 사용자당 분당 10회 |

### Enum

| Enum | 값 |
| --- | --- |
| `Role` | `STUDENT`, `TEACHER`, `ADMIN` |
| `ScoreType` | `JOB_BASIC`(직업기초능력), `MAJOR_SKILL`(전공직무능력), `CHARACTER_JOB_ETHIC`(인성·직업윤리), `HUMANITIES_LITERACY`(인문학적 소양), `FOREIGN_LANGUAGE`(외국어능력) |
| `PointType` | `MERIT`, `DEMERIT` |
| `ContestScope` | `IN_SCHOOL`, `OUT_SCHOOL` |
| `EvidenceStatus` | `PENDING`, `APPROVED`, `REJECTED` |
| `AnalysisStatus` | `PROCESSING`, `DONE`, `FAILED` |
| `SelfReportStatus` | `UNREAD`, `READ`, `IN_PROGRESS`, `DONE` |
| `SelfReportType` | `LOST_FOUND`, `SCHOOL_RULE`, `PEER_RELATION`, `COUNSELING`, `ETC` |
| `PreferredHandling` | `MEETING`, `WRITTEN_REPLY`, `NOTICE_ONLY` |
| `FontScale` | `XS`(85%), `S`(92%), `M`(100%), `L`(115%), `XL`(130%) |
| `BackgroundType` / `BackgroundFit` | `NONE`, `GIF`, `MP4` / `COVER`, `TILE`, `CONTAIN` |
| `DrawType` / 핀볼 `mode` | `SEAT`, `PINBALL` / `DROP`, `BUMPER` |
| `RecommendType` | `VALUE`, `HIGH_SCORE`, `SHORT_TERM` |
| `ScheduleType` | `EXAM`, `PROJECT`, `EVENT` |

Enum은 `app/common/enums.py`(신규) 한곳에 모아 두고 모델·스키마가 함께 쓴다.

## 5. DB 설계

### 5.1. 노션 원본 테이블

| 테이블 | 주요 컬럼 |
| --- | --- |
| `Users` | `user_id` UUID PK, `google_id` UK, `name`, `email` UK, `role` |
| `Students` | `student_id` PK·FK→Users, 영역별 점수 5개(`job_basic_point` …), `total_merit_points` |
| `MeisterScoreDetails` | `meister_point_id` PK, `teacher_id`, `student_id`, `score_type`, `content`(50), `points`, `created_at` |
| `MeritPointDetails` | `merit_point_id` PK, `teacher_id`, `student_id`, `title`(20), `content`(50), `points`, `created_at` |
| `SelfReport` | `report_id` PK, `student_id`, `content`(100), `created_at`, `is_processed` |
| `Contests` | `contest_id` INT PK, `author`, `contest_name`(30), `content`, `start_at`, `finish_at` |
| `ContestTags` / `ContestTaggings` | 분야 태그(`tag_name` 10자 UK) / 대회–태그 N:M |
| `ContestBookmarks` | PK(`student_id`, `contest_id`) |

### 5.2. 구현에 필요한 보완 사항 (노션 공통 규칙 8절 + 각 API의 DB 매핑)

| 구분 | 변경 |
| --- | --- |
| 학번 | `Students.grade`, `class_no`, `student_number` 추가, 세 컬럼 UNIQUE |
| 사전 등록 명단 | `Users.google_id` NULL 허용 (UNIQUE 유지). 첫 로그인 때 이메일로 찾아 `sub` 저장 |
| 프로필 | `Users.profile_image_url`, `Students.github_url`, `Students.linkedin_url` |
| 교사 | `Teachers`(`teacher_id` PK·FK, `subject`, `position`, `homeroom_grade`, `homeroom_class`) |
| 마역량 총점 | 5개 영역 합으로 계산. 성능 문제 시 `total_meister_points` + 인덱스 |
| 평가항목·환산 | `MeisterScoreItems`(`item_id`, `score_type`, `name`, `max_points`, `description`), `MeisterGradeCriteria`, `MeisterScoreDetails.item_id` |
| 증빙자료 | `Evidences`(`evidence_id`, `student_id`, `title`, `description`, `file_url`, `file_name`, `content_type`, `status`, `analysis_status`, `ai_result` JSON, `reject_reason`, `reviewed_by`, `reviewed_at`, `created_at`), `MeisterScoreDetails.evidence_id` NULL |
| 상벌점 기준 | `PointRules`(`rule_id`, `type`, `category`, `title`, `points`, `description`, `note`, `is_active`). 기준 변경은 기존 행 비활성화 + 새 행 |
| 상·벌점 구분 | `MeritPointDetails.points` 부호(상점 +, 벌점 −)로 구분, 합계는 내역에서 계산. 필요 시 `rule_id` NULL 추가 |
| 대회 | `Contests.scope`, `category_id` FK, `expected_score`, `difficulty`, `prep_hours`, `is_verified` |
| 대회 카테고리 | `ContestCategories`(`category_id`, `name`, `normalized_name` UK, `is_default`, `created_by`, `created_at`) |
| 학사 일정 | `AcademicSchedules`(`schedule_id`, `type`, `title`, `start_date`, `end_date`) |
| 추천 가이드라인 | `RecommendationGuidelines`(단일 행, `prompt_guideline`, `exam_buffer_days`, `version`) |
| 자진 신고 | `SelfReport`에 `type`, `title`, `preferred_handling`, `status`, `change_reason`, `updated_at` 추가, `content` TEXT(암호문), `is_processed` → `status`. `SelfReportRecipients`(`report_id`, `teacher_id`, `read_at`), `SelfReportAttachments`(`report_id` NULL, `uploader_id`, …), `SelfReportReplies` |
| 테마 | `UserThemes`(`user_id` PK), `ThemeAssets`, `ThemePresets` |
| 알림 | `Notifications`(`notification_id`, `user_id`, `type`, `title`, `body`, `target_url`, `is_read`, `created_at`), 인덱스 (`user_id`, `is_read`, `created_at`) |
| 뽑기 | `Draws`(`draw_id`, `type`, `mode`, `grade`, `class_no`, `seed`, `options` JSON, `result` JSON, `previous_draw_id`, `created_by`, `created_at`) |
| FK 권장 | `teacher_id`·`author`·`reviewed_by` → `Users`, `SelfReport.student_id` → `Students` |
| 오탈자 | `MeisterScoreDetails.mesiter_point_id` → `meister_point_id` |

스키마 변경은 모두 Alembic 마이그레이션으로 한다. 기본 카테고리·상벌점 기준·평가항목·테마 프리셋은 시드 데이터로 넣는다.

## 6. 도메인별 API

### 6.1. auth / user — 로그인·내 정보·프로필 링크

| Method | URL | 권한 |
| --- | --- | --- |
| GET | `/auth/google?redirect=` | 비로그인 |
| GET | `/auth/google/callback` | 비로그인 |
| POST | `/auth/logout` | 로그인 (세션 없어도 204) |
| GET | `/api/me` | 로그인 |
| GET / PATCH | `/api/me/profile` | 로그인 / 학생 |
| GET | `/api/students/{studentId}` | 로그인 |
| GET | `/api/teachers?q=&subject=&position=` | 로그인 |
| GET | `/api/classes/{grade}/{classNo}/students` | 로그인 |

- 로그인: `state`·`nonce`·PKCE `code_verifier`를 임시 세션에 저장, `scope=openid email profile`, `hd=bssm.hs.kr`, `prompt=select_account`.
- 콜백 검증: `state` 일치 → 토큰 교환 → ID 토큰(서명·`iss`·`aud`·`exp`·`nonce`) → `email_verified`, 토큰의 `hd`, 이메일 도메인 **모두 서버에서 재검사** → `sub`로 조회, 없으면 이메일로 사전 등록 명단 조회.
- 콜백 실패는 JSON이 아니라 `302 /login?error=DOMAIN_NOT_ALLOWED|NOT_REGISTERED|AUTH_FAILED|GOOGLE_UNAVAILABLE`, 사용자 취소는 `302 /login`. 성공 기본 이동은 `/ranking`.
- `redirect`는 `/`로 시작하는 내부 경로만 허용 (오픈 리다이렉트 방지, `//evil.com` 거부).
- 구글 토큰은 저장하지 않는다.
- 프로필 링크 PATCH: 키 없음 = 변경 없음, `null`/빈 문자열 = 삭제, 두 필드는 원자적으로 저장. 정규화 규칙(호스트 정확히 일치, GitHub 아이디 1~39자, LinkedIn `/in/{id}` 3~100자, http/https 외 스킴·계정정보 URL·시스템 경로 거부)과 `reason` 코드(`INVALID_HOST`, `MISSING_ID`, `INVALID_ID`, `NOT_PERSONAL_PROFILE`, `RESERVED_PATH`, `INVALID_SCHEME`)는 노션 `[API] 프로필 링크` 그대로. 순수 함수로 분리해 단위 테스트한다.
- 학급 명단: 학년 1~3, 반 1~4 밖은 `404 CLASS_NOT_FOUND`.

### 6.2. merit — 마역량 랭킹·세부 조회·점수 부여

| Method | URL | 권한 |
| --- | --- | --- |
| GET | `/api/meister/rankings?grade=&page=` | 로그인 |
| GET | `/api/students/{studentId}/meister-scores` | 로그인 |
| GET | `/api/students/{studentId}/meister-scores/history?scoreType=&order=&page=` | 로그인 (증빙은 본인·교사만) |
| GET | `/api/meister/grade-criteria` | 로그인 |
| GET | `/api/meister/score-items?scoreType=` | 로그인 |
| GET | `/api/teacher/students?q=&grade=&classNo=&number=&page=` | 교사 |
| POST | `/api/evidences` (multipart) | 학생 |
| GET | `/api/me/evidences?status=&page=` | 학생 |
| GET | `/api/teacher/evidences?status=PENDING&studentId=&page=` | 교사 |
| GET | `/api/evidences/{evidenceId}` | 제출 학생·교사 (그 외 404) |
| GET | `/api/evidences/{evidenceId}/file` | 제출 학생·교사 |
| POST | `/api/evidences/{evidenceId}/analysis` | 교사 (202) |
| POST | `/api/evidences/{evidenceId}/approve` | 교사 |
| POST | `/api/evidences/{evidenceId}/reject` | 교사 |
| POST | `/api/meister-scores` | 교사 (201) |
| GET | `/api/teacher/meister-scores?studentId=&teacherId=&scoreType=&from=&to=&page=` | 교사 |

- 랭킹: 총점 = 5개 영역 합. `RANK()` (동점 같은 순위, 1·2·2·4), 정렬은 총점 desc → 학년 → 반 → 번호 asc. 전체·학년별 따로 계산, 페이지 크기 20 고정. `page`가 잘못되면 오류 대신 1페이지 + `page: 1`. `grade`가 1~3 밖이면 400. `myRank`(학생만, 아니면 `null`)와 `isMe`(학생 ID로 비교)를 포함한다.
- 영역별 점수는 항상 5개 영역을 모두 반환. 환산 기준이 없으면 `criteriaRegistered: false`, `convertedScore`·`grade`는 `null`.
- 학생 ID가 없거나 UUID 형식이 아니면 `404 STUDENT_NOT_FOUND`.
- 증빙 제출: JPG·PNG·PDF, 10MB 이하, 제목 1~50자. 저장 후 AI 분석을 **비동기**로 시작하고 즉시 201 (`analysisStatus: PROCESSING`, 프론트는 3초 폴링).
- 승인은 **한 트랜잭션**: `PENDING` 확인 → 평가항목 최대 인정 점수 검증(기존 획득분 포함, `400 EXCEEDS_MAX_POINTS` + `remainingPoints`) → 중복 인정 확인(`409 DUPLICATE_ACHIEVEMENT`) → `MeisterScoreDetails` 저장 + `Students.{영역}_point` 가산 → `APPROVED` → `EVIDENCE_APPROVED` 알림. 이미 처리된 증빙은 `409 EVIDENCE_ALREADY_REVIEWED`. 동시 승인에 대비해 행 잠금(`SELECT … FOR UPDATE`) 또는 조건부 UPDATE.
- 반려: 사유 1~200자 필수, `EVIDENCE_REJECTED` 알림.
- 직접 부여: 같은 검증, 음수(감점) 허용하되 영역 점수가 0 미만이면 `400 SCORE_BELOW_ZERO`, `MEISTER_SCORE_CHANGED` 알림. `teacherId=me` 지원.

### 6.3. mileage — 상벌점

| Method | URL | 권한 |
| --- | --- | --- |
| GET | `/api/point-rules?type=&category=&q=` | 로그인 |
| GET | `/api/students/{studentId}/merit-points?groupBy=none\|teacher` | 본인 학생·교사 (다른 학생 403) |
| POST | `/api/merit-points` | 교사 (201) |

- 기준 조회: `is_active = true`만, 정렬 상점→벌점 → 분류 → 점수 desc. 잘못된 `type`은 무시하고 전체 조회. `category`는 반복 파라미터(OR), `q`는 trim 후 최대 50자. `categories`는 필터와 무관하게 전체. `Cache-Control: no-cache` + `ETag`(변경 없으면 304). 페이지 없음.
- 내역 응답의 `points`는 항상 양수, 구분은 `merits`/`demerits` 또는 `type`. `meritTotal`, `demeritTotal`, `net` 포함.
- 부여: 벌점은 음수로 저장, `Students.total_merit_points` 반영.

### 6.4. contest — 대회·카테고리·북마크·학사 일정

| Method | URL | 권한 |
| --- | --- | --- |
| GET / POST | `/api/contest-categories` | 로그인 / 교사 |
| GET | `/api/contests?scope=&categoryId=&page=` | 로그인 |
| GET | `/api/contests/{contestId}` | 로그인 |
| POST | `/api/contests` | 교사 (201 + `Location`) |
| PUT / DELETE | `/api/contests/{contestId}` | 작성 교사·관리자 |
| PUT / DELETE | `/api/contests/{contestId}/bookmark` | 학생 (멱등, 204) |
| GET | `/api/me/bookmarks?page=` | 학생 |
| GET | `/api/academic-schedules?from=&to=` | 로그인 |

- 카테고리 추가: trim 후 1~20자, 한글·영문·숫자·공백·`- · & ( )`만. `normalized_name`(공백 제거 + 영문 소문자)으로 중복 판정 → 있으면 `200` + `created: false`, 없으면 `201` + `created: true`. UNIQUE 충돌 시 기존 행을 다시 읽어 200. `reason`: `EMPTY`/`TOO_LONG`/`INVALID_CHARACTER`.
- 카테고리 정렬: 기본(시드 순) → 추가(가나다순).
- 대회 목록: 마감 가까운 순, 종료된 대회는 뒤로. `dDay`, `isBookmarked`(교사는 항상 false). 없는 `categoryId`·잘못된 `scope`는 400.
- 등록·수정 검증: `contestName` 1~30자, `scope` 필수(기본값 없음), `categoryId` 존재, `startAt ≤ finishAt`. 추천용 필드(`expectedScore`, `difficulty`, `prepHours`, `isVerified`)도 수정 API로 관리.
- 삭제 시 북마크·태깅 행도 같은 트랜잭션에서 삭제.

### 6.5. recommend — 대회 추천 LLM

| Method | URL | 권한 |
| --- | --- | --- |
| POST | `/api/contest-recommendations` | 학생 |
| POST | `/api/contest-recommendations/chat` | 학생 (JSON 또는 `text/event-stream`) |
| GET / PUT | `/api/admin/recommendation-guidelines` | 관리자 |

- 학년·영역별 점수는 서버가 주입 (클라이언트가 바꿀 수 없음).
- 후보: `finish_at ≥ 오늘` + `is_verified`. 시험 기간 전후 `examBufferDays`(기본 7) 이내 마감은 기본 제외, `includeExamPeriod`면 포함 + `scheduleWarnings`.
- **LLM 결과 검증**: 응답의 `contestId`가 후보에 없으면 제거, 점수·마감·난이도는 DB 값으로 덮어쓴다. `efficiencyScore = expectedScore / prepHours`로 정렬.
- LLM 시간 초과 30초 → `502 UPSTREAM_ERROR`. 추천할 대회 없음은 `200` + 빈 배열 + `message`.
- 챗: 메시지 1~1,000자, `conversationId`로 이어감, 대화는 Redis에 30분. 만료·타인 대화는 404. SSE는 `delta` 이벤트 후 `done`(`conversationId` 포함).
- 가이드라인 PUT은 낙관적 잠금: `version` 불일치 시 `409 VERSION_CONFLICT`.
- LLM 클라이언트(`llm_client.py`)와 프롬프트(`prompts.py`)는 분리하고 테스트에서는 가짜 클라이언트로 교체한다.

### 6.6. report — 자진 신고

| Method | URL | 권한 |
| --- | --- | --- |
| GET | `/api/self-reports/default-recipient` | 학생 |
| POST | `/api/self-reports/attachments` (multipart) | 학생 |
| POST | `/api/self-reports` | 학생 |
| GET | `/api/me/self-reports?status=&page=` | 학생 |
| GET | `/api/teacher/self-reports?status=&page=` | 교사 |
| GET / PATCH / DELETE | `/api/self-reports/{reportId}` | 작성자·수신 교사 / 작성자 / 작성자 |
| PATCH | `/api/self-reports/{reportId}/status` | 수신 교사 |
| GET / POST | `/api/self-reports/{reportId}/replies` | 작성자·수신 교사 |
| GET | `/api/self-reports/{reportId}/attachments/{attachmentId}` | 작성자·수신 교사 |

- **비공개 원칙**: 작성 학생과 수신 교사 외에는 모든 API가 `404` (관리자 포함). 모든 쿼리에 작성자/수신자 조건을 넣는다.
- 상태 흐름: `UNREAD` → (수신 교사 첫 상세 조회) `READ` → `IN_PROGRESS` → `DONE`, 또는 `READ → DONE`. 그 외 `409 INVALID_STATUS_TRANSITION`. 교사 첫 답변 시 `READ → IN_PROGRESS` 자동. `DONE` 이후 답변은 `409 REPORT_CLOSED`.
- 수정·철회는 `UNREAD`에서만, `WHERE status = 'UNREAD'` 조건부 UPDATE로 처리 → 실패 시 `409 REPORT_ALREADY_READ`. 철회 시 첨부·수신 교사 알림도 삭제.
- 기본 수신자: 담임 → 학년 부장 → 상담교사 순 대체 (`isFallback`, `fallbackReason`).
- 제출 검증: 제목 1~50자, 내용 1~2,000자, 수신자 1~N명(기본 N=1, 설정값), 중복 불가, 교사 아님 `400 INVALID_RECIPIENT`, 초과 `400 TOO_MANY_RECIPIENTS`, 첨부 최대 3개(본인이 올린 미연결 파일만).
- 첨부: JPG·PNG·PDF, 개당 10MB, 암호화 저장, 24시간 내 미연결 파일 자동 삭제, 다운로드 시 `Cache-Control: no-store`.
- **보안**: 제목·내용·답변·첨부는 AES-256-GCM 암호화 (키는 환경변수/별도 보관). 알림·이메일·로그에 제목·내용·첨부 이름을 남기지 않는다.

### 6.7. theme — 테마 커스텀

| Method | URL | 권한 |
| --- | --- | --- |
| GET / PUT / DELETE | `/api/me/theme` | 로그인 |
| GET | `/api/theme/presets?type=` | 로그인 |
| POST | `/api/me/theme/assets` (multipart) | 로그인 (201) |
| DELETE | `/api/me/theme/assets/{assetId}` | 본인 (아니면 404) |

- 설정이 없으면 기본값: `type NONE`, `opacity 100`, `dim 0`, `blur 0`, `fontScale M`, `textShadow true`, `pauseOnLowPower true`, `autoplayOnDataSaver false`.
- PUT 검증: PRESET/UPLOAD와 `presetId`/`assetId`·종류 불일치 → `400 INVALID_BACKGROUND`, `opacity`·`dim`·`blur` 0~100. MP4의 `fit`은 항상 `COVER`로 저장.
- DELETE(초기화)는 업로드 파일을 지우지 않는다. 현재 배경 파일을 삭제하면 배경만 `NONE`.
- 업로드: GIF 10MB / MP4 30MB·30초 이하(`400 VIDEO_TOO_LONG`), 사용자당 5개(`409 ASSET_LIMIT_EXCEEDED`), 첫 프레임 썸네일 생성, MP4 오디오 트랙 제거 (ffmpeg 필요).

### 6.8. game — 핀볼·자리뽑기

| Method | URL | 권한 |
| --- | --- | --- |
| POST | `/api/draws/seats` | 교사, 해당 학급 학생 (201) |
| POST | `/api/draws/pinball` | 교사, 해당 학급 학생 (201) |
| GET | `/api/draws?grade=&classNo=&type=&limit=` | 로그인 (기본 10, 최대 50) |
| GET | `/api/draws/{drawId}` | 로그인 |
| GET | `/api/draws/{drawId}/verification` | 로그인 |

- **결과는 서버가 결정**: `secrets`로 시드 생성 → SHA-256 카운터 모드 PRNG + Fisher-Yates(알고리즘 v1) → 입력·시드·결과 저장. 같은 입력+시드면 항상 같은 결과가 나와야 한다 (결정성 테스트 필수). `random` 모듈 사용 금지.
- 자리뽑기: 제외 학생 제거 → 고정 자석 먼저 배치 → 나머지 셔플. `avoidPreviousSeat`이면 최대 100회 재시도, 못 피하면 201 + `warnings: ["PREVIOUS_SEAT_UNAVOIDABLE"]`. 오류: `NOT_ENOUGH_SEATS`, `FIXED_SEAT_CONFLICT`, `STUDENT_NOT_IN_CLASS`. 교실 1~10 × 1~10.
- 핀볼: `winnerCount`가 대상보다 많으면 `400 NOT_ENOUGH_CANDIDATES`. `allowDuplicate=false`면 `previousDrawId`부터 이어진 라운드의 당첨자 제외 (다른 학급·종류면 400).
- 검증 응답의 `candidates`는 번호 오름차순, 이름 없이 번호만. `resultHash` 포함.
- `pinball.py`, `seat.py`는 DB 없는 순수 로직으로 두고 service가 호출한다.

### 6.9. notification — 알림 (신규 도메인)

| Method | URL | 권한 |
| --- | --- | --- |
| GET | `/api/notifications?unreadOnly=&cursor=&size=` | 로그인 (size 최대 50, 커서) |
| GET | `/api/notifications/unread-count` | 로그인 |
| PATCH | `/api/notifications/{notificationId}/read` | 본인 (멱등 204, 남의 것 404) |
| PATCH | `/api/notifications/read-all` | 로그인 (204) |
| GET | `/api/notifications/stream` | 로그인 (SSE) |

- 알림 종류: `EVIDENCE_APPROVED`, `EVIDENCE_REJECTED`, `MEISTER_SCORE_CHANGED`, `SELF_REPORT_RECEIVED`(교사, 이메일도 발송), `SELF_REPORT_STATUS_CHANGED`, `SELF_REPORT_REPLIED`.
- 알림을 만드는 공개 API는 없다. 각 도메인 service가 `notification.service.create(...)`를 **원인 처리와 같은 트랜잭션**에서 호출하고, 커밋 후 SSE·이메일 발송.
- SSE: `notification` 이벤트 + 30초 `ping`, `Last-Event-ID`로 재연결 시 누락분 전송. 여러 프로세스면 Redis pub/sub.
- 보관 기간 90일 (정리 작업 필요).

## 7. 개발 단계

| 단계 | 내용 | 완료 기준 |
| --- | --- | --- |
| **Phase 0 기반** | 의존성 추가(SQLAlchemy, Alembic, MySQL 드라이버, joserfc 등), `Settings`, DB 세션, `AppException` + 오류 핸들러(422→400 변환 포함), 페이지·커서 스키마, camelCase 베이스 스키마, Enum 모음, Alembic 초기 마이그레이션, 테스트 픽스처(테스트 DB, 로그인 사용자 주입) | `/health` 외 공통 오류 형식 테스트 통과 |
| **Phase 1 인증·사용자** | Google OIDC + PKCE, 세션(인메모리, Redis로 교체 가능), `get_current_user`/`require_role`, Origin 검사, 요청 제한 유틸, `/api/me`, 사전 등록 명단 시드, `Teachers` | 로그인·로그아웃·`/api/me`·401/403 테스트 |
| **Phase 2 마역량 조회·상벌점** | 랭킹, 학생 기본 정보, 영역별 점수, 내역, 환산 기준, 상벌점 기준·내역·부여 | 랭킹 동점·페이지 규칙, 공개 범위 테스트 |
| **Phase 3 점수 부여** | 평가항목, 파일 저장소 추상화, 증빙 업로드(매직바이트 검사), 검토 목록·상세, 승인·반려·직접 부여, 부여 이력, 알림 테이블 + 생성 service | 최대 점수·중복·상태 충돌 테스트 |
| **Phase 4 대회·프로필** | 카테고리, 대회 CRUD, 태그, 북마크, 학사 일정, 프로필 링크 정규화, 교사 검색, 학급 명단 | 카테고리 정규화·URL 정규화 단위 테스트 |
| **Phase 5 자진 신고·알림** | 암호화 유틸, 첨부(24시간 정리), 신고 CRUD·상태 흐름·답변, 알림 목록·읽음·SSE, 이메일 발송 | 비공개 404, 상태 전이, 동시 수정 409 테스트 |
| **Phase 6 테마·뽑기** | 테마 설정·프리셋·업로드(썸네일, 오디오 제거), 자리뽑기·핀볼·히스토리·검증 | 뽑기 결정성·제약 테스트 |
| **Phase 7 AI** | OCR + LLM 증빙 분석(백그라운드 작업, 재분석), 대회 추천(RAG, 결과 검증), 챗(SSE), 가이드라인 관리 | 가짜 LLM으로 후보 외 대회 제거 테스트 |

앞 단계의 공통 요소(인증, 오류 형식, 알림 service)를 뒤 단계가 재사용한다. 단계 안의 순서는 바꿔도 되지만 Phase 0·1은 먼저 끝낸다.

### 구현 현황

- **Phase 0~6 구현 완료.** 노션 `[API]` 명세 중 Phase 7을 뺀 **67개 엔드포인트**가 모두 있다 (OpenAPI 경로와 명세 목록을 대조해 확인). 노션 기능 명세 12개까지 읽고 재검수해 보완했다. 테스트 152개 통과.
- **Phase 7(AI)은 미구현.** 남은 것:
  - `POST /api/contest-recommendations`, `POST /api/contest-recommendations/chat`, `GET`·`PUT /api/admin/recommendation-guidelines`
  - 증빙 AI 분석의 실제 구현: `app/domains/merit/analyzer.py`의 `EvidenceAnalyzer`를 구현해 `set_analyzer()`로 연결. 지금 기본값은 `DisabledAnalyzer`라 분석이 `FAILED`로 끝나고 교사가 직접 판단한다.
  - LLM 호출: `app/domains/recommend/llm_client.py`의 `LLMClient` 인터페이스만 있다.
  - `RecommendationGuidelines` 테이블과 Alembic 마이그레이션 추가.
- 운영 전에 할 일: 구글 OAuth 값(`GOOGLE_CLIENT_ID` 등), `ENCRYPTION_KEY`, `SERVICE_ORIGINS`, `DATABASE_URL`(MySQL), `AUTO_CREATE_TABLES=false` + `alembic upgrade head`, `SEED_ON_STARTUP=false`로 바꾸고 학교 기준표로 평가항목·상벌점 기준·환산 등급·학사 일정·테마 프리셋 입력, 사전 등록 명단은 `scripts/import_roster.py`, 평가항목·환산 등급·상벌점 기준·학사 일정·테마 배경 갤러리·대회 태그는 `scripts/import_reference.py`(형식: `scripts/reference.example.json`)로 입력. 이메일을 보내려면 `SMTP_*`를 설정한다(비우면 로그만).

### 알려진 제한

- **푸시(FCM) 미구현**: 자진 신고 접수는 인앱 알림 + 이메일만. 노션 알림 API 명세가 모바일 푸시를 앱 출시 시점으로 미뤘다.
- **MP4 오디오 제거·썸네일은 서버에 `ffmpeg`가 있을 때만** 동작한다. 없으면 원본을 그대로 저장하고 썸네일은 `null` (프론트가 음소거 재생).
- 평가항목·환산 기준·상벌점 기준·학사 일정을 등록·수정하는 API는 없다 (명세가 별도 관리 기능으로 미룸). 가져오기 스크립트로만 넣는다.
- 알림 기능 명세 페이지가 비어 있어 알림 종류·문구는 `[API]` 명세의 도출안이다.

### 구현하면서 정한 것 (노션에 없던 부분)

- **중복 인정 판정**: 같은 학생 + 같은 평가항목 + 공백·대소문자를 무시한 `content`가 같으면 `409 DUPLICATE_ACHIEVEMENT`. 감점(음수)은 검사하지 않는다. 증빙 상세의 `duplicateSuspect`는 AI가 읽은 실적명이 기존 내역 `content`에 *포함*되는지로 보는 힌트다.
- **최대 인정 점수**: 같은 학생·항목의 기존 내역 합계(감점 포함) + 새 점수 ≤ 항목 `max_points`.
- **승인 동시성**: 학생 행을 `SELECT … FOR UPDATE`로 잠그고, 증빙 상태는 `WHERE status='PENDING'` 조건부 UPDATE (0행이면 409). 실패하면 트랜잭션 전체가 롤백된다.
- **자진 신고**: 수신자 한 명이 열면 `READ`. `hasNewReply`는 답변의 `is_read`(상대방이 읽었는지)로 계산. 관리자도 수신자가 아니면 404. 교사가 확인 전(`UNREAD`)에 답변하면 `READ`를 거쳐 `IN_PROGRESS`로 간다.
- **뽑기**: 입력·결과는 학생 **번호** 기준으로 저장(`Draw.options`/`result`)하고, 결과에는 이름 스냅샷도 함께 둔다. 검증 응답은 이름 없이 번호만. `game/service.replay()`로 시드에서 결과를 다시 계산할 수 있다.
- **알림**: `notification.service.add()`로 같은 트랜잭션에 저장하고 `commit()`이 커밋한 뒤 SSE로 내보낸다. 롤백하면 발행하지 않는다.
- **`/api/me`**: 학생은 `student`, 교사·관리자는 `teacher`(담임 학년·반 포함)를 준다. 뽑기 화면이 담임 학급을 기본값으로 채우는 데 쓴다.
- **평가항목별 점수**: `GET /api/students/{id}/meister-scores`의 `areas[].items[]`에 항목별 획득 점수(감점 포함 합계, 점수 없으면 0)를 함께 준다.
- **세션 쿠키**: 운영은 `Secure`. 로컬 http에서 테스트하려면 `COOKIE_SECURE=false`.
- **Origin 검사**: 변경 요청에 `Origin` 헤더가 없으면 403 (서버 간 호출·curl도 헤더를 붙여야 한다). `ENFORCE_ORIGIN=false`로 끌 수 있다.
- **시간**: DB에는 KST naive datetime으로 저장하고 응답은 `+09:00`으로 직렬화 (`common/timeutil.py`, `KstDateTime`).

## 8. 미확정·임시값

노션에서 "임의로 정한 값"으로 표시된 항목. 하드코딩하지 말고 `config.py` 설정이나 상수 한곳에 모은다.

- 오류 `code` 이름, `/login?error=` 코드 이름, 응답 래퍼 없는 형식
- 요청 제한 값 (대회 추천, 파일 업로드)
- 마역량 영역 한글 이름, 환산 방식(원점수 × 비율)과 등급 기준 → 학교 기준표 확인 필요
- 증빙 파일 형식·10MB, 제목 50자, 반려 사유 200자, AI 분석 폴링 3초, 중복 인정 강제 불가
- 상·벌점 구분 방식(부호 vs `type` 컬럼)
- 카테고리를 별도 테이블로 둔 결정, 대회 수정·삭제 권한(작성 교사·관리자)
- LLM 시간 초과 30초, 대화 보관 30분, 전공·기술 스택은 요청 본문으로 받음
- 자진 신고 수신자 N=1, 한 명이라도 열면 `READ`, 첫 답변 시 `IN_PROGRESS`, 첨부 24시간 정리
- 테마 MP4 30초·업로드 5개·GIF 10MB
- 뽑기 권한(교사 + 해당 학급 학생), 히스토리 기본 10개, 교실 최대 10×10
- 알림 종류·문구·`targetUrl`, 보관 90일, 모바일 푸시는 추후 (알림 기능 명세가 아직 비어 있음)

## 9. 작업 규칙

- 노션 명세와 다르게 구현해야 하면 먼저 사용자에게 확인하고, 바뀐 내용은 이 문서에도 반영한다.
- 새 테이블·컬럼은 Alembic 마이그레이션으로만 추가한다.
- 권한 검사는 라우터 의존성(`require_role`)과 service의 소유자 검사(본인·작성자·수신자)를 함께 쓴다. 숨겨야 하는 자원은 403이 아니라 404.
- 파일 형식은 확장자가 아니라 파일 내용(매직 바이트)으로 판별한다.
- 시간은 DB에 UTC 또는 KST 중 하나로 통일해 저장하고, 응답은 항상 `+09:00`으로 직렬화한다.
- 비밀값(구글 클라이언트 시크릿, 암호화 키, LLM 키)은 `.env`에만 두고 `.env.example`에는 키 이름만 적는다.

### 명령

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

```bash
.venv/bin/uvicorn app.main:app --reload
```

```bash
.venv/bin/pytest
```

```bash
.venv/bin/alembic upgrade head
```

```bash
.venv/bin/python -m scripts.import_roster roster.csv
```
